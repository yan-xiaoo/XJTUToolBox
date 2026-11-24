import threading

from PyQt5.QtCore import pyqtSignal, pyqtSlot

from notification.site_search import SearchCancelled, search
from .ProcessWidget import ProcessThread
from ..utils import logger


class SiteSearchThread(ProcessThread):
    """在已订阅的通知来源里调用各站自己的全文检索。"""
    results = pyqtSignal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyword = ""
        self.source_ids: list[str] = []
        # 本地已有通知的 (来源, 链接)，用来把全站检索结果归到频道
        self.known: list[tuple[str, str]] = []
        # 用户规则的二次过滤，一般是 NotificationManager.satisfy_filter
        self.accept = None
        self._cancel = threading.Event()

    @pyqtSlot()
    def onStopSignal(self):
        super().onStopSignal()
        self._cancel.set()

    def run(self):
        self.can_run = True
        self._cancel = threading.Event()
        keyword = self.keyword
        self.progressChanged.emit(0)
        self.messageChanged.emit(self.tr("正在各网站站内搜索「{keyword}」...").format(keyword=keyword))
        self.setIndeterminate.emit(True)
        try:
            result = search(self.source_ids, keyword, known=self.known, accept=self.accept, cancel=self._cancel)
        except SearchCancelled:
            self.canceled.emit()
            return
        except Exception as e:
            logger.error("站内搜索失败", exc_info=True)
            self.error.emit(self.tr("站内搜索失败"), str(e))
            self.canceled.emit()
            return
        if not self.can_run:
            self.canceled.emit()
            return
        if result.errors:
            failed = list(result.errors.items())
            details = "\n".join(f"{source}: {error}" for source, error in failed[:3])
            if len(failed) > 3:
                details += self.tr("\n另有 {count} 个网站失败").format(count=len(failed) - 3)
            self.error.emit(self.tr("部分网站搜索失败"), details)
        self.results.emit(keyword, result.notifications)
        self.hasFinished.emit()
