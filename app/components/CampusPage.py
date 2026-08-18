from PyQt5.QtWidgets import QFrame, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, ScrollArea, StrongBodyLabel, TableWidget, TitleLabel

from app.threads.CampusFeatureThread import CampusFeatureThread
from app.threads.ProcessWidget import ProcessWidget
from app.utils import StyleSheet, accounts


class CampusPage(ScrollArea):
    """Shared chrome for newly ported campus tools."""

    def __init__(self, object_name: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 40)
        self.vBoxLayout.setSpacing(10)
        self.titleLabel = TitleLabel(title, self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.minorLabel = StrongBodyLabel(subtitle, self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.vBoxLayout.addWidget(self.minorLabel)

        self.jobSlot = QWidget(self.view)
        self.jobLayout = QVBoxLayout(self.jobSlot)
        self.jobLayout.setContentsMargins(0, 0, 0, 0)
        self.jobLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.jobSlot)
        self.thread = None
        self.processWidget = None

        StyleSheet.EMPTY_ROOM_INTERFACE.apply(self)
        self.setWidgetResizable(True)
        self.setWidget(self.view)
        self._notice = None

    def add_toolbar(self, *widgets) -> QFrame:
        bar = QFrame(self.view)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for widget in widgets:
            if widget is not None:
                layout.addWidget(widget)
        layout.addStretch(1)
        self.vBoxLayout.addWidget(bar)
        return bar

    def labeled(self, text: str, widget: QWidget, width: int = 56) -> QFrame:
        box = QFrame(self.view)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = BodyLabel(text, box)
        label.setFixedWidth(width)
        layout.addWidget(label)
        layout.addWidget(widget)
        return box

    def make_table(self, headers: list[str]) -> TableWidget:
        table = TableWidget(self.view)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setWordWrap(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(TableWidget.SelectRows)
        return table

    def start_job(self, site_key: str, message: str, worker, on_result, need_login: bool = True,
                  show_process: bool = True) -> bool:
        if self.thread is not None and self.thread.isRunning():
            self.thread.can_run = False
        self.thread = CampusFeatureThread(site_key, message, worker, need_login=need_login, parent=self)
        if self.processWidget:
            self.processWidget.deleteLater()
            self.processWidget = None
        if show_process:
            self.processWidget = ProcessWidget(self.thread, self.jobSlot, hide_on_end=True)
            self.jobLayout.addWidget(self.processWidget)
        self.thread.result.connect(on_result)
        self.thread.error.connect(self.warn)
        self.thread.start()
        return True

    def require_account(self) -> bool:
        if accounts.current is None:
            self.warn(self.tr("未登录"), self.tr("请先添加一个账户"))
            return False
        return True

    def info(self, title: str, msg: str) -> None:
        self._bar(InfoBar.info, title, msg)

    def success(self, title: str, msg: str) -> None:
        self._bar(InfoBar.success, title, msg)

    def warn(self, title: str, msg: str) -> None:
        self._bar(InfoBar.warning, title, msg)

    def _bar(self, factory, title: str, msg: str) -> None:
        if self._notice is not None:
            try:
                self._notice.close()
            except RuntimeError:
                self._notice = None
        self._notice = factory(title, msg, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self)
