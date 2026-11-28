from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QFrame, QHBoxLayout

from ..utils import accounts, cfg
from ..utils.account import IncorrectAccountPassword
from ..utils.account_storage import AccountStorageError
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, PasswordLineEdit, BodyLabel, PrimaryPushButton, InfoBar


class EncryptDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("加密账户"), self)
        self.hint = CaptionLabel(self.tr("设置后，每次启动应用都需要输入此密码。\n"
                                         "请记住密码，忘记后将无法解锁账户信息。"), self)
        self.passwordEdit = PasswordLineEdit(self)
        self.passwordEdit.setPlaceholderText(self.tr("输入加密密码"))

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.passwordEdit)

        self.yesButton.setText(self.tr("加密"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    @pyqtSlot()
    def _onYesButtonClicked(self):
        if not self.passwordEdit.text():
            return
        try:
            accounts.setEncrypted(True, self.passwordEdit.text().encode(), use_keyring=cfg.useKeyring.value)
        except (AccountStorageError, ValueError) as exc:
            InfoBar.error(self.tr("账户加密失败"), str(exc), parent=self)
            return
        self.accept()


class DecryptDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("解密账户"), self)
        self.hint = CaptionLabel(self.tr("请输入解密账户所需的密码"), self)
        self.passwordEdit = PasswordLineEdit(self)
        self.passwordEdit.setPlaceholderText(self.tr("输入密码"))
        self.failHint = CaptionLabel(self)
        self.failHint.setVisible(False)
        self.failHint.setTextColor(QColor(255, 0, 0), QColor(255, 0, 0))
        # 记录输入密码失败的次数
        self.failCount = 0
        self.setMinimumWidth(300)

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.passwordEdit)
        self.viewLayout.addWidget(self.failHint)

        self.yesButton.setText(self.tr("解密"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

    def showError(self, text):
        self.failHint.setText(text)
        self.failHint.setVisible(True)

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    @pyqtSlot()
    def _onYesButtonClicked(self):
        if not self.passwordEdit.text():
            self.showError(self.tr("密码不能为空"))
            return

        try:
            warning = accounts.unlock(self.passwordEdit.text().encode())
        except IncorrectAccountPassword:
            self.failCount += 1
            if self.failCount >= 3:
                self.showError(self.tr("密码错误。如果你忘记了密码，可以通过设置-清除账户信息清空账户并撤销加密。"))
            else:
                self.showError(self.tr("密码错误"))
            return
        except AccountStorageError as exc:
            self.showError(str(exc))
            return

        if warning is not None:
            InfoBar.warning(self.tr("账户已解锁"), str(warning), duration=-1, isClosable=True, parent=self.parentWidget())
        self.failCount = 0
        self.accept()



class DecryptFrame(QFrame):
    def __init__(self, window_parent, parent=None):
        super().__init__(parent)
        self.window_parent = window_parent

        self.hBoxLayout = QHBoxLayout(self)
        self.label = BodyLabel(self.tr("账户已经加密"), self)
        self.button = PrimaryPushButton(self.tr("点击解密"), self)
        self.button.clicked.connect(self.onButtonClicked)

        self.hBoxLayout.addWidget(self.label)
        self.hBoxLayout.addSpacing(20)
        self.hBoxLayout.addWidget(self.button)

    def setVisible(self, visible):
        super().setVisible(visible)
        self.label.setVisible(visible)
        self.button.setVisible(visible)

    @pyqtSlot()
    def onButtonClicked(self):
        w = DecryptDialog(self.window_parent)
        w.exec()
