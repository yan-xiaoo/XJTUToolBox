from PyQt5.QtCore import Qt, QUrl, pyqtSlot
from PyQt5.QtGui import QDesktopServices, QColor
from qfluentwidgets import BodyLabel, FluentStyleSheet, MessageBoxBase, SubtitleLabel, LineEdit, \
    CaptionLabel


class MessageBoxHtml(MessageBoxBase):
    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.contentLabel = BodyLabel(content, parent)
        self.contentLabel.setObjectName("contentLabel")
        self.contentLabel.setOpenExternalLinks(True)
        self.contentLabel.linkActivated.connect(self.open_url)
        self.contentLabel.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.contentLabel.setWordWrap(True)

        FluentStyleSheet.DIALOG.apply(self.contentLabel)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.contentLabel)

    @pyqtSlot(str)
    def open_url(self, url):
        QDesktopServices.openUrl(QUrl(url))


class MessageBoxUpdate(MessageBoxHtml):
    def __init__(self, title: str, content: str, can_download: bool = True, parent=None):
        super().__init__(title, content, parent)

        if can_download:
            self.yesButton.setText(self.tr('下载'))
        else:
            self.yesButton.setText(self.tr('前往更新'))
        self.cancelButton.setText(self.tr('好的'))


class ConfirmBox(MessageBoxBase):
    """
    此对话框用于确认较为重要的操作，如删除操作等
    用户需要在对话框中输入指定的文字，才能确认操作
    """
    def __init__(self, title: str, body: str, type_: str, hint: str = None, parent=None):
        """
        :param title: 对话框标题
        :param body: 对话框正文
        :param type_: 用户需要输入的文字
        :param hint: 输入框的提示文字
        """
        super().__init__(parent)
        self.required_type = type_
        self.hint = hint

        self.titleLabel = SubtitleLabel(title, self)
        self.bodyLabel = BodyLabel(body, self)
        self.typeEdit = LineEdit()
        self.typeEdit.setPlaceholderText(hint)
        self.typeEdit.setClearButtonEnabled(True)

        self.failHint = CaptionLabel(self)
        self.failHint.setVisible(False)
        self.failHint.setTextColor(QColor(255, 0, 0), QColor(255, 0, 0))

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.bodyLabel)
        self.viewLayout.addWidget(self.typeEdit)
        self.viewLayout.addWidget(self.failHint)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

        # 设置对话框的最小宽度
        self.widget.setMinimumWidth(300)

        self.typeEdit.setFocus()

    @pyqtSlot()
    def _onYesButtonClicked(self):
        if self.typeEdit.text() != self.required_type:
            self.failHint.setText(self.hint)
            self.failHint.setVisible(True)
            self.typeEdit.setError(True)
            self.typeEdit.clear()
            self.typeEdit.setFocus()
        else:
            self.typeEdit.setError(False)
            self.accept()
            self.accepted.emit()

    def keyReleaseEvent(self, a0):
        if a0.key() == Qt.Key_Return:
            self.yesButton.click()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()
        else:
            super().keyReleaseEvent(a0)