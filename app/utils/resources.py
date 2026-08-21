"""Resolve bundled and source-tree application resources."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str | Path) -> Path:
    """Return an absolute path for a source or PyInstaller resource.

    PyInstaller exposes the unpacked bundle root as ``sys._MEIPASS``.  In a
    source checkout resources live beside the repository's Python packages.
    """

    relative_path = Path(relative)
    if relative_path.is_absolute():
        return relative_path
    bundle_root = getattr(sys, "_MEIPASS", None)
    root = Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]
    return root / relative_path
