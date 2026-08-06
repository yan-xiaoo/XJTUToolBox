"""Launch the Qt 6 Jiaoxiaozhi browser without mixing Qt major versions."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def school_ai_browser_command() -> tuple[str, list[str]] | None:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        suffix = ".exe" if os.name == "nt" else ""
        helper = executable.parent / "SchoolAIBrowser" / f"SchoolAIBrowser{suffix}"
        return (str(helper), []) if helper.is_file() else None
    if importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is None:
        return None
    return sys.executable, ["-m", "app.school_ai_browser"]
