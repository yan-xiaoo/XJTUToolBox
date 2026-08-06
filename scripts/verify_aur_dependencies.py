#!/usr/bin/env python3
"""Verify every PKGBUILD dependency against the official repos or AUR.

The dependency list is read from ``makepkg --printsrcinfo`` so this check does
not need a second, hand-maintained package list.  It is intended for both local
release checks and the AUR publishing workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_PACKAGES = (
    Path("aur/xjtutoolbox"),
    Path("aur/xjtutoolbox-bin"),
    Path("aur/xjtutoolbox-git"),
)
DEPENDENCY_KEYS = {"depends", "makedepends", "checkdepends"}
VERSION_OPERATOR = re.compile(r"[<>=].*$")
USER_AGENT = "XJTUToolbox-AUR-dependency-check/1"


def request_json(url: str, attempts: int = 5) -> dict:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as caught:
            error = caught
            if attempt + 1 < attempts:
                time.sleep(min(2**attempt, 5))
    raise RuntimeError(f"无法读取 {url}: {error}") from error


def srcinfo(directory: Path) -> str:
    result = subprocess.run(
        ["makepkg", "--printsrcinfo"],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def dependencies(directory: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in srcinfo(directory).splitlines():
        key, separator, value = raw_line.strip().partition(" = ")
        if separator and key.split("_", 1)[0] in DEPENDENCY_KEYS:
            name = VERSION_OPERATOR.sub("", value).strip()
            if name:
                names.add(name)
    return names


def official_package(name: str) -> dict | None:
    payload = request_json(
        "https://archlinux.org/packages/search/json/?" + urlencode({"name": name})
    )
    return next(
        (row for row in payload.get("results", []) if row.get("pkgname") == name),
        None,
    )


def aur_packages(names: list[str]) -> dict[str, dict]:
    if not names:
        return {}
    query = "&".join(f"arg[]={quote(name)}" for name in names)
    payload = request_json("https://aur.archlinux.org/rpc/v5/info?" + query)
    return {row["Name"]: row for row in payload.get("results", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directories", nargs="*", type=Path, default=DEFAULT_PACKAGES,
        help="directories containing PKGBUILD files",
    )
    args = parser.parse_args()

    owners: dict[str, list[str]] = {}
    for directory in args.directories:
        if not (directory / "PKGBUILD").is_file():
            parser.error(f"缺少 {directory / 'PKGBUILD'}")
        for name in dependencies(directory):
            owners.setdefault(name, []).append(directory.name)

    official: dict[str, dict] = {}
    unresolved: list[str] = []
    for name in sorted(owners):
        row = official_package(name)
        if row is None:
            unresolved.append(name)
        else:
            official[name] = row
    aur = aur_packages(unresolved)
    missing = sorted(set(unresolved) - set(aur))

    for name in sorted(owners):
        used_by = ",".join(sorted(owners[name]))
        if name in official:
            row = official[name]
            location = f"official/{row['repo']} {row['pkgver']}-{row['pkgrel']}"
        elif name in aur:
            location = f"AUR {aur[name]['Version']}"
        else:
            location = "MISSING"
        print(f"{name:<32} {location:<32} [{used_by}]")

    if missing:
        print("\n不存在的依赖：" + "、".join(missing), file=sys.stderr)
        return 1
    print(f"\nOK: {len(owners)} 个唯一依赖均存在于 Arch 官方仓库或 AUR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
