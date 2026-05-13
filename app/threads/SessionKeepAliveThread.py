from __future__ import annotations

from PyQt5.QtCore import QThread, QObject

from app.utils.account import Account
from app.utils.log import logger
from app.utils.session_manager import KeepAliveReport


class SessionKeepAliveThread(QThread):
    """在后台线程中执行当前账号的 Session 保活。"""

    def __init__(self, account: Account, parent: QObject | None = None) -> None:
        """创建后台 Session 保活线程。"""
        super().__init__(parent)
        self.account = account
        self.report: KeepAliveReport | None = None

    def run(self) -> None:
        """执行一次后台 Session 保活。"""
        try:
            self.report = self.account.session_manager.keep_alive_logged_in_sessions(self.account.uuid)
        except Exception:
            logger.exception("后台 Session 保活线程执行失败")
