# -*- coding: utf-8 -*-
"""Sports venue booking slider captcha solver.

The server cuts a puzzle piece out of the background image and returns
both the background (JPEG) and the cut piece (PNG RGBA). The client must
detect the gap position and submit a simulated slider track.

Algorithm: edge-NCC (normalized cross-correlation on binary edge maps).
"""

from __future__ import annotations

import base64
import io
import json
import random
import sys
import time as _time_module
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image

from app.venues.venue import VenueUtil

BASE = VenueUtil.BASE_URL
SERVER_BG_W = 260
CHECK_URL_SUFFIX = f"{VenueUtil.PAY_BASE_URL}:8071"


# ---------------------------------------------------------------------------
# Fetch captcha
# ---------------------------------------------------------------------------

def fetch_captcha(session: requests.Session | None = None):
    """GET /gen and return (captcha_id, bg_rgb, slider_rgba)."""
    s = session or requests
    r = s.get(f"{BASE}/gen", timeout=12)
    r.raise_for_status()
    data = r.json()
    cap = data["captcha"]
    bg = np.array(Image.open(io.BytesIO(
        base64.b64decode(cap["backgroundImage"].split(",")[1]))).convert("RGB"))
    sl = np.array(Image.open(io.BytesIO(
        base64.b64decode(cap["sliderImage"].split(",")[1]))).convert("RGBA"))
    return data["id"], bg, sl


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def _piece_bbox(slider_rgba: np.ndarray, thr: int = 50):
    """Find piece bounding box from alpha channel -> (y0, y1, x0, x1)."""
    alpha = slider_rgba[:, :, 3]
    ys, xs = np.where(alpha > thr)
    if xs.size == 0:
        return None
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def _sobel(img: np.ndarray) -> np.ndarray:
    """Pure numpy Sobel gradient magnitude. Input: float32 2D."""
    p = np.pad(img, 1, mode="edge")
    gx = (p[0:-2, 2:] - p[0:-2, 0:-2]
          + 2.0 * (p[1:-1, 2:] - p[1:-1, 0:-2])
          + (p[2:, 2:] - p[2:, 0:-2]))
    gy = ((p[0:-2, 0:-2] + 2.0 * p[0:-2, 1:-1] + p[0:-2, 2:])
          - (p[2:, 0:-2] + 2.0 * p[2:, 1:-1] + p[2:, 2:]))
    return np.sqrt(gx * gx + gy * gy)


def detect_gap(bg_rgb: np.ndarray, slider_rgba: np.ndarray) -> tuple[int, float]:
    """Detect gap, return (move_x, confidence).

    move_x is the slider displacement in server coordinate space (0-260).
    """
    bg_w = bg_rgb.shape[1]
    bbox = _piece_bbox(slider_rgba)
    if bbox is None:
        return 0, 0.0
    y0, y1, x0, x1 = bbox

    piece_gray = slider_rgba[y0:y1 + 1, x0:x1 + 1, :3].astype(np.float32).mean(axis=2)
    bg_gray = bg_rgb.astype(np.float32).mean(axis=2)

    bg_edge = _sobel(bg_gray)
    pe = _sobel(piece_gray)
    bg_bin = (bg_edge > bg_edge.mean() + bg_edge.std() * 0.6).astype(np.float32)
    pe_bin = (pe > pe.mean() + pe.std() * 0.6).astype(np.float32)

    band = bg_bin[y0:y1 + 1, :]
    pw = pe_bin.shape[1]
    width = band.shape[1]

    tmpl = pe_bin - pe_bin.mean()
    tmpl_norm = np.sqrt((tmpl * tmpl).sum()) + 1e-6

    best_ncc, best_x = -1e9, 0
    for x in range(width - pw + 1):
        win = band[:, x:x + pw]
        win0 = win - win.mean()
        ncc = float((win0 * tmpl).sum()
                    / (tmpl_norm * (np.sqrt((win0 * win0).sum()) + 1e-6)))
        if ncc > best_ncc:
            best_ncc, best_x = ncc, x

    # move_x in 260-based server coordinate space
    move_x = (best_x - x0) * SERVER_BG_W / bg_w
    return int(round(max(move_x, 0.0))), float(best_ncc)


# ---------------------------------------------------------------------------
# Track generation
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_track(move_x: int) -> dict:
    """Generate human-like slider track mimicking real mouse drag."""
    start_t = random.randint(800, 1500)
    track: list[dict] = [{"x": 0, "y": 0, "type": "down", "t": start_t}]

    target = float(move_x)
    t = start_t + random.randint(100, 200)
    # ~60fps, easeOutCubic, no overshoot (matches HAR pattern)
    duration = random.randint(1000, 1400)
    steps = max(duration // 16, 20)
    for i in range(1, steps + 1):
        progress = i / steps
        eased = 1 - (1 - progress) ** 3  # easeOutCubic
        x = round(target * eased)
        y = random.randint(-2, 2)
        track.append({"x": x, "y": y, "type": "move", "t": t})
        t += random.randint(12, 20)

    # pause before release (HAR shows ~500ms)
    t += random.randint(400, 600)
    track.append({"x": int(round(target)), "y": random.randint(-3, 0),
                  "type": "up", "t": t})

    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(milliseconds=(t - start_t))
    return {
        "bgImageWidth": SERVER_BG_W,
        "bgImageHeight": 0,
        "sliderImageWidth": 0,
        "sliderImageHeight": 159,
        "startSlidingTime": _iso(start_dt),
        "entSlidingTime": _iso(now),
        "trackList": track,
    }


def build_yzm(track: dict, captcha_id: str) -> str:
    """Build yzm string: ``{track JSON}synjones{captchaId}synjones{url}``"""
    track_json = json.dumps(track, separators=(",", ":"))
    return f"{track_json}synjones{captcha_id}synjones{CHECK_URL_SUFFIX}"


# ---------------------------------------------------------------------------
# One-shot solve
# ---------------------------------------------------------------------------

def solve(session: requests.Session | None = None):
    """Fetch captcha, detect gap, generate track. Returns (yzm, track, cid, conf)."""
    cid, bg, sl = fetch_captcha(session)
    move_x, conf = detect_gap(bg, sl)
    track = gen_track(move_x)
    return build_yzm(track, cid), track, cid, conf


def verify(track: dict, captcha_id: str,
           session: requests.Session | None = None) -> bool:
    """Verify track via /check endpoint (self-test only)."""
    s = session or requests
    track_json = json.dumps(track, separators=(",", ":"))
    r = s.post(f"{BASE}/check?id={captcha_id}",
               data=track_json,
               headers={"Content-Type": "application/json"}, timeout=10)
    return r.text.strip().lower() == "true"


# ---------------------------------------------------------------------------
# CLI batch test
# ---------------------------------------------------------------------------

def main(n: int = 80):
    ok = fail = 0
    for i in range(n):
        try:
            _, track, cid, conf = solve()
            success = verify(track, cid)
            if success:
                ok += 1
            else:
                fail += 1
            print(f"[{i:02d}] conf={conf:.3f} {'OK' if success else 'FAIL'}")
        except Exception as e:
            print(f"[{i:02d}] ERR {e}")
        _time_module.sleep(0.25)
    total = ok + fail
    rate = ok / total * 100 if total else 0.0
    print(f"\n=== n={total} ok={ok} fail={fail} rate={rate:.1f}% ===")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
