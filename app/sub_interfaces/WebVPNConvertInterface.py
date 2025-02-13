import sys

from PyQt5.QtCore import pyqtSlot, QTimer, QUrl
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QApplication
from qfluentwidgets import ScrollArea, TransparentToolButton, \
    TransparentPushButton, TitleLabel, StrongBodyLabel, PlainTextEdit, InfoBarPosition, InfoBar, CaptionLabel, \
    HyperlinkLabel
from qfluentwidgets import FluentIcon as FIF
from auth.util import getVPNUrl, getOrdinaryUrl

from app.utils import StyleSheet


class WebVPNConvertInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("webvpn_convert_interface")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 40)

        self.titleLabel = TitleLabel(self.tr("WebVPN 网址转换"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.minorLabel = StrongBodyLabel(self.tr("将 WebVPN 网址转换为正常网址"), self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.vBoxLayout.addWidget(self.minorLabel)
        self.vBoxLayout.addSpacing(10)

        self.webvpnFrame = QFrame(self.view)
        self.webvpnLayout = QHBoxLayout(self.webvpnFrame)
        self.webvpnEdit = PlainTextEdit(self.webvpnFrame)
        self.webvpnEdit.setPlaceholderText(self.tr("WebVPN 网址"))
        self.webvpnCopyButton = TransparentToolButton(FIF.COPY, self.webvpnFrame)
        self.webvpnCopyButton.setFixedSize(24, 24)

        self.webvpnLayout.addWidget(self.webvpnEdit)
        self.webvpnLayout.addWidget(self.webvpnCopyButton)

        self.buttonFrame = QFrame(self.view)
        self.buttonLayout = QHBoxLayout(self.buttonFrame)
        self.decodeButton = TransparentPushButton(FIF.DOWN, self.tr("解析"), self.buttonFrame)
        self.encodeButton = TransparentPushButton(FIF.UP, self.tr("生成"), self.buttonFrame)
        self.buttonLayout.addWidget(self.decodeButton)
        self.buttonLayout.addWidget(self.encodeButton)

        self.normalFrame = QFrame(self.view)
        self.normalLayout = QHBoxLayout(self.normalFrame)
        self.normalEdit = PlainTextEdit(self.normalFrame)
        self.normalEdit.setPlaceholderText(self.tr("正常网址"))
        self.normalCopyButton = TransparentToolButton(FIF.COPY, self.normalFrame)
        self.normalCopyButton.setFixedSize(24, 24)

        self.normalLayout.addWidget(self.normalEdit)
        self.normalLayout.addWidget(self.normalCopyButton)

        self.labelFrame = QFrame(self.view)
        self.labelLayout = QVBoxLayout(self.labelFrame)
        self.label = CaptionLabel(self.tr("正在寻找网址转换的 Python API？请查看"), self.labelFrame)
        self.link = HyperlinkLabel(QUrl("https://github.com/ESWZY/webvpn-dlut"), self.tr("GitHub 仓库"), self.labelFrame)
        self.labelLayout.addWidget(self.label)
        self.labelLayout.addWidget(self.link)

        self.vBoxLayout.addWidget(self.webvpnFrame)
        self.vBoxLayout.addWidget(self.buttonFrame)
        self.vBoxLayout.addWidget(self.normalFrame)
        self.vBoxLayout.addWidget(self.labelFrame)

        self.webvpnCopyButton.clicked.connect(self.onWebVPNCopyButtonClicked)
        self.normalCopyButton.clicked.connect(self.onNormalCopyButtonClicked)
        self.decodeButton.clicked.connect(self.onDecodeButtonClicked)
        self.encodeButton.clicked.connect(self.onEncodeButtonClicked)

        StyleSheet.WEBVPN_CONVERT_INTERFACE.apply(self)
        self.setWidgetResizable(True)
        self.setWidget(self.view)
        self._onlyNotice = None
        self._timer = None

    def error(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个错误的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if parent is None:
            parent = self

        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)

    def warning(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个警告的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if parent is None:
            parent = self

        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        self._onlyNotice = InfoBar.warning(title, msg, duration=duration, position=position, parent=parent)

    @pyqtSlot()
    def onWebVPNCopyButtonClicked(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.webvpnEdit.toPlainText())
        self.webvpnCopyButton.setIcon(FIF.ACCEPT)
        # 1s 后恢复图标
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(lambda: self.webvpnCopyButton.setIcon(FIF.COPY))
        self._timer.start()

    @pyqtSlot()
    def onNormalCopyButtonClicked(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.normalEdit.toPlainText())
        self.normalCopyButton.setIcon(FIF.ACCEPT)
        # 1s 后恢复图标
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(lambda: self.normalCopyButton.setIcon(FIF.COPY))
        self._timer.start()

    @pyqtSlot()
    def onDecodeButtonClicked(self):
        url = self.webvpnEdit.toPlainText()
        if not url:
            return
        try:
            self.normalEdit.setPlainText(getOrdinaryUrl(url))
        except Exception as e:
            print(e)
            self.error("", self.tr("网址格式错误"))

    @pyqtSlot()
    def onEncodeButtonClicked(self):
        url = self.normalEdit.toPlainText()
        if not url:
            return
        try:
            self.webvpnEdit.setPlainText(getVPNUrl(url))
        except Exception:
            self.error("", self.tr("网址格式错误"))
