from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, LineEdit, PrimaryPushButton, \
    BodyLabel, InfoBar, CheckBox


class VerifyCodeDialog(MessageBoxBase):
    """用户选择发送手机验证码的对话框"""
    # 发送输入的验证码+是否可信
    codeSignal = pyqtSignal(str, bool)
    # 点击发送按键的信号
    sendSignal = pyqtSignal()

    def __init__(self, phone_number: str, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("两步验证"), self)
        self.hint = CaptionLabel(self.tr("登录系统认为当前登录环境异常，需通过安全验证确定是本人操作后才可继续登录"), self)

        self.sendLayout = QHBoxLayout()
        self.phoneNumberDisplay = BodyLabel(phone_number, self)

        self.sendButton = PrimaryPushButton(self.tr("发送验证码"), self)
        self.sendLayout.addWidget(self.phoneNumberDisplay, stretch=1)
        self.sendLayout.addWidget(self.sendButton)

        self.codeEdit = LineEdit(self)
        self.codeEdit.setPlaceholderText(self.tr("请输入验证码"))

        self.warningHint = CaptionLabel(self.tr("验证码应当是 6 位的数字"), self)
        self.warningHint.setTextColor(QColor(255, 0, 0), QColor(255, 0, 0))
        self.warningHint.setVisible(False)

        self.trustCheckBox = CheckBox(self.tr("登录成功后，设为可信客户端"), self)
        self.trustCheckBox.setChecked(True)

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addLayout(self.sendLayout)
        self.viewLayout.addWidget(self.codeEdit)
        self.viewLayout.addWidget(self.warningHint)
        self.viewLayout.addWidget(self.trustCheckBox)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

        self.sendButton.clicked.connect(self._onSendButtonClicked)
        # 点击发送后，60 秒内不能再发送。
        self.resendTimer = QTimer(self)
        self.resendTimer.setInterval(1000)
        self.resendTimer.timeout.connect(self.__onResendTimer)
        self._countDown = 0

        # 结果
        self.code: Optional[str] = None
        self.trust: bool = True

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    def _onYesButtonClicked(self):
        # 设置结果
        data = self.codeEdit.text()
        if not data:
            self.codeEdit.setError(True)
            self.codeEdit.setFocus()
            return
        elif len(data) != 6 or not data.isdigit():
            self.codeEdit.setError(True)
            self.codeEdit.setFocus()
            self.warningHint.setVisible(True)
            return

        self.code = data
        self.trust = self.trustCheckBox.isChecked()
        self.codeSignal.emit(self.code, self.trustCheckBox.isChecked())
        self.accept()
        self.accepted.emit()

    @pyqtSlot()
    def _onSendButtonClicked(self):
        self.sendSignal.emit()
        self.sendButton.setEnabled(False)
        self.yesButton.setEnabled(False)
        self._countDown = 60
        self.resendTimer.start()

    @pyqtSlot()
    def __onResendTimer(self):
        self._countDown -= 1
        if self._countDown < 0:
            self.resendTimer.stop()
            self.sendButton.setText(self.tr("发送验证码"))
            self.sendButton.setEnabled(True)
        else:
            self.sendButton.setText(self.tr("重新发送（{0}）").format(self._countDown))

    def reportSendResult(self, success: bool, msg: str = ""):
        """
        报告发送验证码的结果。如果发送失败，则重新启用发送按钮，并显示错误信息
        """
        self.yesButton.setEnabled(True)
        if success:
            self.warningHint.setVisible(False)
        else:
            if msg:
                InfoBar.error(self.tr("发送失败"), msg, parent=self, duration=3000)
            self.resendTimer.stop()
            self.sendButton.setText(self.tr("发送验证码"))
            self.sendButton.setEnabled(True)
