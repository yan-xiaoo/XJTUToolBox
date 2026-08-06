from PyQt5.QtCore import pyqtSignal, Qt, QUrl, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QSizePolicy
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, CheckBox, PushButton, PrimaryPushButton

from notification.source import get_source_name, get_source_url, normalize_source_id, source_registry


class NoticeSourceCard(CardWidget):
    """
    显示通知来源的卡片，并且可以通过打勾管理是否启用来源
    """
    # 当自身选择状态发生变化时的信号
    # 第一个参数为是否选中，第二个参数为稳定来源 ID
    checkChanged = pyqtSignal(bool, str)
    # 当设置规则按钮被点击时的信号
    setRuleClicked = pyqtSignal(str)

    def __init__(self, source: str, checked=False, parent=None):
        super().__init__(parent)

        self.source = normalize_source_id(source)
        self.descriptor = source_registry.get(self.source)
        self.available = self.descriptor is not None and self.descriptor.verified

        self.titleLabel = BodyLabel(get_source_name(self.source), self)
        detail = get_source_url(self.source)
        if self.descriptor is None:
            detail = self.tr("未知来源：配置已保留，可取消订阅")
        elif self.descriptor.status == "empty":
            detail = f"{detail}  ·  {self.tr('栏目当前为空，暂不可订阅')}"
        elif not self.descriptor.verified:
            detail = f"{detail}  ·  {self.tr('待核验，暂不可订阅')}"
        self.contentLabel = CaptionLabel(detail, self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.contentLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.titleLabel.setToolTip(self.titleLabel.text())
        self.contentLabel.setToolTip(detail)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 20, 11)
        self.hBoxLayout.setSpacing(15)

        self.checkBox = CheckBox(self)
        self.checkBox.setChecked(checked)
        # A stale unavailable subscription may still be unchecked by the user.
        self.checkBox.setEnabled(self.available or checked)
        self.checkBox.clicked.connect(self.onCheckboxClicked)
        self.hBoxLayout.addWidget(self.checkBox)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)

        self.browseButton = PushButton(self.tr("前往"), self)
        self.browseButton.setEnabled(bool(get_source_url(self.source)))
        self.browseButton.clicked.connect(self.onBrowseButtonClicked)
        self.addRuleButton = PrimaryPushButton(self.tr("设置过滤规则"), self)
        self.addRuleButton.clicked.connect(lambda: self.setRuleClicked.emit(self.source))

        self.actionLayout = QHBoxLayout()
        self.actionLayout.setContentsMargins(0, 4, 0, 0)
        self.actionLayout.setSpacing(8)
        self.actionLayout.addStretch(1)
        self.actionLayout.addWidget(self.browseButton)
        self.actionLayout.addWidget(self.addRuleButton)
        self.vBoxLayout.addLayout(self.actionLayout)
        self.hBoxLayout.addLayout(self.vBoxLayout, stretch=1)

        self.changeRulesetButtonState()

    @pyqtSlot()
    def onBrowseButtonClicked(self):
        QDesktopServices.openUrl(QUrl(get_source_url(self.source)))

    def mousePressEvent(self, event):
        """
        鼠标点击事件，更改启用状态
        """
        if event.button() == Qt.LeftButton and self.checkBox.isEnabled():
            self.checkBox.setChecked(not self.checkBox.isChecked())
            self.checkBox.clicked.emit()
        super().mousePressEvent(event)

    def changeRulesetButtonState(self):
        """
        根据当前启用状态更改规则按钮的可用性。如果整张通知卡片没有被启用，那么“设置过滤规则”按钮不可用
        """
        self.addRuleButton.setEnabled(self.available and self.checkBox.isChecked())

    @pyqtSlot()
    def onCheckboxClicked(self):
        """
        当复选框被点击时，发出信号
        """
        self.changeRulesetButtonState()
        self.checkChanged.emit(self.checkBox.isChecked(), self.source)
