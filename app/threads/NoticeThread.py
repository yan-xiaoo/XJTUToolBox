import requests
from PyQt5.QtCore import pyqtSignal

from auth import get_session
from notification import NotificationManager
from .ProcessWidget import ProcessThread
from ..utils import logger


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
        try:
            notices = self.notice_manager.get_notifications(pages=self.pages)
        except requests.ConnectionError:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("无网络连接"), self.tr("请检查网络连接，然后重试。"))
            self.canceled.emit()
        except requests.RequestException as e:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("网络错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
        else:
            if not self.can_run:
                self.canceled.emit()
                return

            self.notices.emit(notices)
            self.hasFinished.emit()
