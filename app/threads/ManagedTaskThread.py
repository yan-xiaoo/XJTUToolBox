"""Cooperative jobs survive window destruction and finish before Qt exits."""
import threading
from PyQt5.QtCore import QCoreApplication, QThread, Qt


class ManagedTaskThread(QThread):
    _active_jobs = set()

    def __init__(self, parent=None):
        super().__init__()
        self._cancel = threading.Event()
        self.finished.connect(self._release)
        if parent is not None:
            parent.destroyed.connect(self.cancel, Qt.DirectConnection)
        application = QCoreApplication.instance()
        if application is not None and not getattr(application, '_managed_tasks_connected', False):
            application.aboutToQuit.connect(ManagedTaskThread.shutdown_all)
            application._managed_tasks_connected = True

    def start(self, priority=QThread.InheritPriority):
        self._active_jobs.add(self)
        try:
            super().start(priority)
        except Exception:
            self._active_jobs.discard(self)
            raise

    def _release(self):
        self._active_jobs.discard(self)

    def cancel(self, *_):
        self._cancel.set()

    @classmethod
    def shutdown_all(cls):
        jobs = tuple(cls._active_jobs)
        for job in jobs:
            job.cancel()
        for job in jobs:
            job.wait()
            cls._active_jobs.discard(job)
