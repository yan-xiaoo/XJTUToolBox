from collections.abc import Callable
from typing import Any

from PyQt5.QtCore import pyqtSignal

from app.threads.ProcessWidget import ProcessThread
from app.utils.campus_job import run_campus_job


class CampusFeatureThread(ProcessThread):
    """Login a campus site (optional) and run a worker on a background thread."""

    result = pyqtSignal(object)

    def __init__(
            self,
            site_key: str,
            login_message: str,
            worker: Callable[[Any], Any],
            need_login: bool = True,
            parent=None):
        super().__init__(parent)
        self.site_key = site_key
        self.login_message = login_message
        self.worker = worker
        self.need_login = need_login

    def run(self):
        payload = run_campus_job(
            self,
            site_key=self.site_key,
            login_message=self.login_message,
            worker=self.worker,
            need_login=self.need_login,
        )
        if payload is None:
            return
        self.result.emit(payload)
        self.hasFinished.emit()
