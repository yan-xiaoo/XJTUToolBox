from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from copy import deepcopy

from PyQt5.QtCore import pyqtSignal
from .ManagedTaskThread import ManagedTaskThread
from xjtu_calendar.fileutil import atomic_write_text
from schedule.calendar_process import run_child


class CalendarThread(ManagedTaskThread):
    result = pyqtSignal(dict)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = deepcopy(request)

    def run(self):
        # Keep request/response files within this account's private data area.
        home = Path(self.request["home"])
        try:
            home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="job-", dir=home) as directory:
                request = Path(directory) / "request.json"
                response = Path(directory) / "response.json"
                atomic_write_text(request, json.dumps(self.request), private=True)
                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--calendar-worker"]
                else:
                    command = [sys.executable, str(Path(__file__).resolve().parents[2] / "app.py"),
                               "--calendar-worker"]
                env = os.environ.copy()
                env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", PYTHONUTF8="1")
                returncode = run_child(
                    [*command, str(request), str(response)],
                    env=env, cancel=self._cancel, timeout=300,
                )
                if not response.is_file():
                    raise RuntimeError(f"日历任务未完成（退出码 {returncode}）")
                result = json.loads(response.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            result = {"ok": False, "message": "发布等待超时，远端状态可能已改变。请先修复发布状态再重试。"}
        except Exception as exc:
            result = {"ok": False, "message": str(exc)}
        self.result.emit(result)
