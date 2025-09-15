import datetime
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, LineEdit, TransparentToolButton, FluentIcon

from auth.util import generate_random_visitor_id


class ResetVisitorIdDialog(MessageBoxBase):
    """设置界面中，选择重置访客 ID 弹出的对话框"""
    # 发送选择的 ID
    visitorIdSignal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("重置登录 ID"), self)
        self.hint = CaptionLabel(self.tr("重置登录时服务器用于标识不同客户端的 ID。\n重置 ID 会导致登录系统将本应用识别为一个新的客户端，可能需要再次进行两步验证。"), self)
        self.hint.setWordWrap(True)
        self.warningHint = CaptionLabel(self.tr("重置后，您当前的登录 ID 将永久失效，无法恢复。"), self)
        self.warningHint.setTextColor(QColor(255, 0, 0), QColor(255, 0, 0))

        self.editLayout = QHBoxLayout()
        self.idEdit = LineEdit(self)
        self.idEdit.setPlaceholderText(self.tr("输入或随机生成一个新 ID"))
        # 保证 ID 可以显示完整
        self.idEdit.setMinimumWidth(300)
        self.randomButton = TransparentToolButton(FluentIcon.FINGERPRINT, self)

        self.failHint = CaptionLabel(self.tr("登录 ID 是长 32 位的 16 进制数，其中 a-e 字母应当小写。"), self)
        self.failHint.setVisible(False)

        self.editLayout.addWidget(self.idEdit, stretch=1)
        self.editLayout.addWidget(self.randomButton)

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.warningHint)
        self.viewLayout.addLayout(self.editLayout)
        self.viewLayout.addWidget(self.failHint)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)
        self.randomButton.clicked.connect(self._onRandomButtonClicked)

        # 结果 ID
        self.visitorId: Optional[str] = None

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    def _onYesButtonClicked(self):
        # 设置结果
        if not self.idEdit.text():
            self.idEdit.setFocus()
            self.idEdit.setError(True)
        else:
            text = self.idEdit.text()
            if len(text) != 32 or not all(c in "0123456789abcdef" for c in text):
                self.idEdit.setFocus()
                self.idEdit.setError(True)
                self.failHint.setVisible(True)
                return

            self.visitorId = self.idEdit.text()
            self.visitorIdSignal.emit(self.visitorId)
            self.accept()
            self.accepted.emit()

    @pyqtSlot()
    def _onRandomButtonClicked(self):
        # 生成一个随机的 visitor ID
        self.idEdit.setText(generate_random_visitor_id())
        self.idEdit.setError(False)
        self.failHint.setVisible(False)
