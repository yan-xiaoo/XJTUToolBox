from PyQt5.QtCore import pyqtSignal, Qt, QUrl, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, CheckBox, PushButton, PrimaryPushButton

from notification import Source
from notification.source import get_source_url


class NoticeSourceCard(CardWidget):
    """
    显示通知来源的卡片，并且可以通过打勾管理是否启用来源
    """
    # 当自身选择状态发生变化时的信号
    # checkChanged: bool, Source
    # 第一个参数为是否选中，第二个参数为对应的 Source
    checkChanged = pyqtSignal(bool, Source)
    # 当设置规则按钮被点击时的信号
    setRuleClicked = pyqtSignal(Source)

    def __init__(self, source: Source, checked=False, parent=None):
        super().__init__(parent)

        self.source = source

        self.titleLabel = BodyLabel(source.value, self)
        self.contentLabel = CaptionLabel(get_source_url(source), self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 20, 11)
        self.hBoxLayout.setSpacing(15)

        self.checkBox = CheckBox(self)
        self.checkBox.setChecked(checked)
        self.checkBox.clicked.connect(self.onCheckboxClicked)
        self.hBoxLayout.addWidget(self.checkBox)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout, stretch=1)

        self.browseButton = PushButton(self.tr("前往"), self)
        self.browseButton.clicked.connect(self.onBrowseButtonClicked)
        self.addRuleButton = PrimaryPushButton(self.tr("设置过滤规则"), self)
        self.addRuleButton.clicked.connect(lambda: self.setRuleClicked.emit(self.source))

        self.hBoxLayout.addWidget(self.browseButton, 0, Qt.AlignRight)
        self.hBoxLayout.addWidget(self.addRuleButton, 0, Qt.AlignRight)

    @pyqtSlot()
    def onBrowseButtonClicked(self):
        QDesktopServices.openUrl(QUrl(get_source_url(self.source)))

    def mousePressEvent(self, event):
        """
        鼠标点击事件，显示通知网页来源
        """
        if event.button() == Qt.LeftButton:
            self.checkBox.setChecked(not self.checkBox.isChecked())
            self.checkBox.clicked.emit()
        super().mousePressEvent(event)

    @pyqtSlot()
    def onCheckboxClicked(self):
        """
        当复选框被点击时，发出信号
        """
        self.checkChanged.emit(self.checkBox.isChecked(), self.source)