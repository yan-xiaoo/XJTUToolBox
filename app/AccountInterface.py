from PyQt5.QtCore import Qt, QPoint, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
from qfluentwidgets import ScrollArea, TitleLabel, VBoxLayout, StrongBodyLabel, BodyLabel, SubtitleLabel, LineEdit, \
    CardWidget, IconWidget, CaptionLabel, PushButton, TransparentToolButton, FluentIcon, RoundMenu, Action, MessageBox, \
    MessageBoxBase, InfoBar

from .sub_interfaces.EncryptDialog import DecryptFrame
from .utils import StyleSheet, cfg, AccountCacheManager
from .utils.account import Account, AccountManager


class AddAccountCard(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.iconWidget = IconWidget(FluentIcon.ADD, self)
        self.titleLabel = BodyLabel(self.tr("添加账户…"), self)
        self.contentLabel = CaptionLabel(self.tr("点击添加一个新的账户"), self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.iconWidget.setFixedSize(48, 48)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)


class AccountCard(CardWidget):
    accountChanged = pyqtSignal()
    accountDeleted = pyqtSignal(Account)
    accountCurrentChanged = pyqtSignal(Account)

    def __init__(self, account: Account, icon, title, content, main_window, parent=None):
        super().__init__(parent)
        self.account = account
        # 获得主窗口的引用，用于切换界面
        self.main_window = main_window
        self.parent_ = parent

        self.iconWidget = IconWidget(icon)
        self.titleLabel = BodyLabel(title, self)
        self.contentLabel = CaptionLabel(content, self)
        self.openButton = PushButton(self.tr('切换'), self)
        self.moreButton = TransparentToolButton(FluentIcon.MORE, self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.iconWidget.setFixedSize(48, 48)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")
        self.openButton.setFixedWidth(120)

        self.hBoxLayout.setContentsMargins(20, 11, 11, 11)
        self.hBoxLayout.setSpacing(15)
        self.hBoxLayout.addWidget(self.iconWidget)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.openButton, 0, Qt.AlignRight)
        self.hBoxLayout.addWidget(self.moreButton, 0, Qt.AlignRight)

        self.editAction = Action(FluentIcon.EDIT, self.tr("编辑名称"), self)
        self.editPasswordAction = Action(FluentIcon.LABEL, self.tr('修改密码'), self)
        self.deleteAction = Action(FluentIcon.DELETE, self.tr('删除'), self)

        self.editAction.triggered.connect(self._onEditAccountNameClicked)
        self.editPasswordAction.triggered.connect(self._onEditAccountPasswordClicked)
        self.deleteAction.triggered.connect(self._onDeleteAccountClicked)

        self.menu = RoundMenu(parent=self)
        self.menu.addAction(self.editAction)
        self.menu.addAction(self.editPasswordAction)
        self.menu.addAction(self.deleteAction)

        self.moreButton.setFixedSize(32, 32)
        self.moreButton.clicked.connect(self.onMoreButtonClicked)
        self.openButton.clicked.connect(self.onOpenButtonClicked)

        self.deleted = False

    def setCurrent(self, is_current: bool):
        """设置此账户卡包含的是当前账户与否。账户卡的样式与此有关。"""
        if not self.deleted:
            if is_current:
                self.openButton.setEnabled(False)
                self.openButton.setText(self.tr('当前账户'))
            else:
                self.openButton.setEnabled(True)
                self.openButton.setText(self.tr('切换'))

    def onOpenButtonClicked(self):
        self.accountCurrentChanged.emit(self.account)

    def onMoreButtonClicked(self):
        x = (self.moreButton.width() - self.menu.width()) // 2 + 10
        pos = self.moreButton.mapToGlobal(QPoint(x, self.moreButton.height()))
        self.menu.exec(pos)

    def _onEditAccountNameClicked(self):
        dialog = EditAccountNameBox(self.parent().parent().parent().parent())
        if dialog.exec():
            self.account.nickname = dialog.nameEdit.text()
            self.titleLabel.setText(self.account.nickname)
            self.accountChanged.emit()

    def _onEditAccountPasswordClicked(self):
        self.main_window.switchTo(self.main_window.login_interface)
        self.main_window.login_interface.userNameEdit.setText(self.account.username)
        self.main_window.login_interface.loginSuccess.connect(self._onLoginFinish)
        self.main_window.login_interface.passwordEdit.setFocus()

    def _onDeleteAccountClicked(self):
        box = MessageBox(self.tr("删除账户"), self.tr("确定要删除此账户吗？\n账户相关的缓存数据会被一同删除，无法恢复。"),
                         self.parent().parent().parent().parent())
        box.yesButton.setText(self.tr("删除"))
        box.cancelButton.setText(self.tr("取消"))
        if box.exec():
            self.accountDeleted.emit(self.account)

    @pyqtSlot(str, str)
    def _onLoginFinish(self, username, password):
        self.account.username = username
        self.account.password = password
        self.titleLabel.setText(self.account.nickname)
        self.main_window.switchTo(self.main_window.account_interface)
        self.accountChanged.emit()
        self.main_window.login_interface.loginSuccess.disconnect()
        self.main_window.login_interface.clearEdits()

    def deleteLater(self):
        self.accountChanged.disconnect()
        self.accountDeleted.disconnect()
        self.accountCurrentChanged.disconnect()
        self.deleted = True
        super().deleteLater()


class EditAccountNameBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr('设置账户名称'), self)
        self.bodyLabel = BodyLabel(self.tr('为账户设置一个名称，用于本地显示'), self)
        self.nameEdit = LineEdit()
        self.nameEdit.setPlaceholderText(self.tr('账户名称'))
        self.nameEdit.setClearButtonEnabled(True)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.bodyLabel)
        self.viewLayout.addWidget(self.nameEdit)
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        # 设置对话框的最小宽度
        self.widget.setMinimumWidth(300)

        self.nameEdit.setFocus()

    def keyReleaseEvent(self, a0):
        if a0.key() == Qt.Key_Return:
            self.yesButton.click()
        else:
            super().keyReleaseEvent(a0)


class AccountInterface(ScrollArea):
    def __init__(self, accounts: AccountManager, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountInterface")
        self.main_window = main_window

        self.main_window.login_interface.cancel.connect(self._onLoginCancel)

        self.view = QWidget(self)
        self.vBoxLayout = VBoxLayout(self.view)
        self.vBoxLayout.setSpacing(5)
        self.vBoxLayout.setContentsMargins(10, 15, 10, 30)
        self.view.setObjectName("scrollWidget")

        self.titleLabel = TitleLabel(self.tr("切换账户"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.minorLabel = StrongBodyLabel(self.tr("选择要切换的账户或添加一个新账户"), self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.vBoxLayout.addWidget(self.minorLabel)
        self.vBoxLayout.addSpacing(10)

        self.decryptFrame = DecryptFrame(main_window, self)
        self.decryptFrame.setMaximumWidth(300)

        self.vBoxLayout.addWidget(self.decryptFrame, alignment=Qt.AlignHCenter)
        if accounts.encrypted:
            self.decryptFrame.setVisible(True)
        else:
            self.decryptFrame.setVisible(False)

        self.accountArea = QFrame(self.view)
        self.accountArea.setObjectName("accountArea")
        self.accountAreaLayout = VBoxLayout(self.accountArea)

        self.accountAreaLayout.setSpacing(6)
        self.accountAreaLayout.setContentsMargins(30, 60, 30, 30)
        self.accountAreaLayout.setAlignment(Qt.AlignTop)

        self.vBoxLayout.addWidget(self.accountArea, stretch=1)

        self.default_icon = QIcon("assets/icons/default_avatar.png")

        self.addAccountWidget = AddAccountCard(self.accountArea)
        self.accountAreaLayout.addWidget(self.addAccountWidget)
        self.addAccountWidget.clicked.connect(self._onAddAccountClicked)

        self.accounts = accounts
        if accounts.encrypted:
            self.accountClickable = False
        else:
            self.accountClickable = True

        accounts.accountDecrypted.connect(self._onAccountDecrypted)
        accounts.accountCleared.connect(self._onAccountCleared)

        self.account_widgets = {}
        for account in self.accounts:
            self._add_account_widget(account, is_current=account == self.accounts.current)

        if accounts.empty():
            self.minorLabel.setText("你还没有任何账户。点击下方添加一个账户")

        self.setWidget(self.view)
        self.setWidgetResizable(True)

        StyleSheet.ACCOUNT_INTERFACE.apply(self)

    @pyqtSlot()
    def _onAccountCleared(self):
        self.decryptFrame.setVisible(False)
        self.accountClickable = True
        for one in self.account_widgets.values():
            self.accountAreaLayout.removeWidget(one)
            one.deleteLater()
        self.account_widgets.clear()

    @pyqtSlot()
    def _onAccountDecrypted(self):
        self.decryptFrame.setVisible(False)
        self.accountClickable = True
        for account in self.accounts:
            self._add_account_widget(account, is_current=account == self.accounts.current)

    def _onAccountChanged(self):
        # 如果没有账户了，则取消加密
        if len(self.accounts) == 0:
            self.accounts.setEncrypted(False)
        self.accounts.save_suitable()

    @pyqtSlot(Account)
    def _onAccountDeleted(self, account: Account):
        if account == self.accounts.current:
            self.accounts.current = self.accounts[0]
            self.accounts.remove(account)
            if len(self.accounts) > 0:
                self._onCurrentAccountChanged(self.accounts[0])
        else:
            self.accounts.remove(account)

        AccountCacheManager(account).remove_all()
        self.accountAreaLayout.removeWidget(self.account_widgets[account])
        self.account_widgets[account].deleteLater()
        self._onAccountChanged()

    def _onAddAccountClicked(self):
        if not self.accountClickable:
            InfoBar.error(self.tr("无法添加账户"), self.tr("请先解密账户"), duration=2000, parent=self)
            return
        if not cfg.hasReadLoginTip.value:
            if not self.show_first_time_tip():
                return
        self.main_window.login_interface.loginSuccess.connect(self._onLoginFinish)
        self.main_window.switchTo(self.main_window.login_interface)
        self.main_window.login_interface.userNameEdit.setFocus()

    def _onLoginCancel(self):
        self.main_window.switchTo(self)
        self.main_window.login_interface.clearEdits()
        self.main_window.login_interface.loginSuccess.disconnect()

    def add_account(self, account: Account):
        self.accounts.append(account)
        self._add_account_widget(account)
        if len(self.accounts) == 1:
            self.accounts.current = account
            self._onCurrentAccountChanged(account)
        self.accounts.save_suitable()

    def _add_account_widget(self, account: Account, is_current=False):
        """is_current 仅仅影响按钮样式，不会影响账户的切换行为"""
        widget = AccountCard(account, self.default_icon, account.nickname, account.username, self.main_window,
                             self.accountArea)
        widget.accountChanged.connect(self._onAccountChanged)
        widget.accountDeleted.connect(self._onAccountDeleted)
        widget.accountCurrentChanged.connect(self._onCurrentAccountChanged)
        self.account_widgets[account] = widget
        self.accountAreaLayout.addWidget(widget)
        widget.setCurrent(is_current)

    @pyqtSlot(Account)
    def _onCurrentAccountChanged(self, account: Account):
        self.accounts.current = account
        for a, w in self.account_widgets.items():
            w.setCurrent(a == account)
        self._onAccountChanged()

    @pyqtSlot(str, str)
    def _onLoginFinish(self, username, password):
        account = Account(username, password, username)
        self.add_account(account)
        self.main_window.switchTo(self)
        self.main_window.login_interface.clearEdits()
        self.main_window.login_interface.loginSuccess.disconnect()

    def show_first_time_tip(self) -> bool:
        """显示第一次使用时的说明"""
        w = MessageBox(self.tr("登录说明"), self.tr("此程序由交大学生个人开发。\n本程序仅会在本地存储用户名和密码信息，并且仅在与西安交通"
                                                    "大学服务器通信时使用这些信息。\n继续使用即代表您已知晓并同意此行为。"),
                       self)
        w.yesButton.setText(self.tr("同意"))
        w.cancelButton.setText(self.tr("不同意"))
        if w.exec():
            cfg.hasReadLoginTip.value = True
            return True
        else:
            return False
