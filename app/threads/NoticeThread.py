from PyQt5.QtCore import pyqtSignal

from auth import get_session
from notification import NotificationManager
from .ProcessWidget import ProcessThread


class NoticeThread(ProcessThread):
    notices = pyqtSignal(list)

    def __init__(self, manager: NotificationManager, pages=1, session=None, parent=None):
        super().__init__(parent)
        self.notice_manager = manager
        if session is None:
            session = get_session()
        self.session = session
        self.pages = pages

    def run(self):
        self.can_run = True

        self.progressChanged.emit(0)
        self.messageChanged.emit(self.tr("正在获取通知..."))
        self.setIndeterminate.emit(True)

        notices = self.notice_manager.get_notifications(pages=self.pages)
        if not self.can_run:
            self.canceled.emit()
            return
        self.notices.emit(notices)
        self.hasFinished.emit()
