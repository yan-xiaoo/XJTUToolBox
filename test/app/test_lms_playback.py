"""Windows playback regression using a tiny synthetic H.264 MP4."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "playback-h264.mp4"

PROBE = textwrap.dedent(r"""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    import re
    import sys
    import threading
    from PyQt5.QtCore import QTimer, QUrl
    from PyQt5.QtMultimedia import QVideoProbe
    from PyQt5.QtWidgets import QApplication
    from app.sub_interfaces.lms.video_page import LMSVideoPage

    payload = Path(sys.argv[1]).read_bytes()
    signed_path = '/control.mp4?response-content-disposition=attachment&signature=' + 'a' * 1500
    requests_seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_HEAD(self):
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def do_GET(self):
            if self.path != signed_path:
                self.send_response(403)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            start, end = 0, len(payload) - 1
            match = re.match(r'bytes=(\d+)-(\d*)', self.headers.get('Range', ''))
            if match:
                start = int(match[1])
                if match[2]:
                    end = min(int(match[2]), end)
            requests_seen.append(self.headers.get('Range'))
            self.send_response(206 if match else 200)
            # RMS downloads may omit Content-Type; keep this response equally sparse.
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Disposition', 'attachment; filename=control.mp4')
            self.send_header('Accept-Ranges', 'bytes')
            if match:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
            self.end_headers()
            try:
                self.wfile.write(payload[start:end + 1])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = None
    if sys.argv[2] == 'http':
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}' + signed_path
    else:
        url = QUrl.fromLocalFile(sys.argv[1]).toString()
    app = QApplication([])
    page = LMSVideoPage()
    page.resize(480, 360)
    page.show()
    player = page.videoWidget.player
    player.setMuted(True)
    probe = QVideoProbe()
    probe.setSource(player)
    frames = 0
    done = False
    def finish():
        global done
        if done:
            return
        done = True
        print('PLAYBACK_RESULT=' + json.dumps({
            'frames': frames, 'duration': player.duration(), 'error': int(player.error()),
            'error_string': player.errorString(), 'requests': requests_seen,
        }), flush=True)
        probe.setSource(None)
        page.stopPlayback()
        page.close()
        page.deleteLater()
        QTimer.singleShot(200, app.quit)
    def on_frame(frame):
        global frames
        frames += 1
        if frames == 3:
            QTimer.singleShot(100, finish)
    probe.videoFrameProbed.connect(on_frame)
    player.error.connect(lambda error: QTimer.singleShot(100, finish))
    QTimer.singleShot(7000, finish)
    page.setReplayVideo({'download_url': url, 'label': 'control'}, 'control')
    app.exec_()
    if server:
        server.shutdown()
    raise SystemExit(0 if frames >= 3 else 1)
""")


@unittest.skipUnless(sys.platform == "win32", "Windows media backend regression")
class LMSPlaybackTest(unittest.TestCase):
    def playback(self, mode):
        environment = os.environ | {
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "PYTHONUTF8": "1",
        }
        environment.pop("QT_MULTIMEDIA_PREFERRED_PLUGINS", None)
        completed = subprocess.run(
            [sys.executable, "-B", "-c", PROBE, str(FIXTURE), mode],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = next(line.removeprefix("PLAYBACK_RESULT=") for line in completed.stdout.splitlines()
                      if line.startswith("PLAYBACK_RESULT="))
        data = json.loads(result)
        self.assertEqual(data["error"], 0)
        self.assertGreater(data["duration"], 0)
        self.assertGreaterEqual(data["frames"], 3)
        return data

    def test_windows_plays_local_h264_mp4(self):
        self.playback("local")

    def test_windows_streams_h264_with_replay_url_constraints(self):
        data = self.playback("http")
        self.assertTrue(data["requests"], "The player must request the video")


if __name__ == "__main__":
    unittest.main()
