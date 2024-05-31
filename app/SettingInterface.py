from PyQt5.QtCore import pyqtSlot
from qfluentwidgets import ScrollArea, ExpandLayout, SettingCardGroup, ComboBoxSettingCard, setTheme, \
    setThemeColor, PrimaryPushSettingCard, PushSettingCard, InfoBar, MessageBox
from qfluentwidgets import FluentIcon as FIF
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QColor

from .utils.config import cfg
from .utils import accounts
from .utils.style_sheet import StyleSheet
from .cards.custom_color_setting_card import CustomColorSettingCard
from .sub_interfaces.EncryptDialog import EncryptDialog, DecryptDialog


class SettingInterface(ScrollArea):
    """设置界面"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("SettingInterface")
        self.view = QWidget(self)
        self.view.setObjectName("scrollWidget")

        self.expandLayout = ExpandLayout(self.view)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

        accounts.accountEncryptStateChanged.connect(self._onUpdateEncryptStatus)

        # 添加设置组
        # 账户设置组
        self.accountGroup = SettingCardGroup(self.tr("账户"), self.view)
        self.encryptCard = PrimaryPushSettingCard(self.tr("加密"), FIF.CERTIFICATE,
                                                  self.tr("加密账户"), self.tr("加密本地存储的账户信息，以免泄漏"),
                                                  self.accountGroup)
        self.decryptCard = PushSettingCard(self.tr("不再加密"), FIF.FINGERPRINT,
                                           self.tr("不再加密账户"), self.tr("撤销账户加密，重新使用明文存储账户信息"),
                                           self.accountGroup)
        self.accountGroup.addSettingCard(self.encryptCard)
        self.accountGroup.addSettingCard(self.decryptCard)

        self._onUpdateEncryptStatus()

        # 考勤设置组
        self.attendanceGroup = SettingCardGroup(self.tr("考勤"), self.view)
        self.loginMethodCard = ComboBoxSettingCard(cfg.defaultAttendanceLoginMethod, FIF.GLOBE,
                                                   self.tr("考勤默认连接方式"),
                                                   self.tr("选择是否默认通过 WebVPN 连接考勤系统"),
                                                   texts=[self.tr("每次都询问"), self.tr("直接连接"),
                                                          self.tr("WebVPN 连接")],
                                                   parent=self.attendanceGroup)
        self.attendanceGroup.addSettingCard(self.loginMethodCard)

        # 个性化组
        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.view)
        self.themeCard = ComboBoxSettingCard(cfg.themeMode, FIF.BRUSH, self.tr("应用主题"),
                                             self.tr("调整应用程序的外观"),
                                             texts=[self.tr("浅色"), self.tr("深色"), self.tr("自动")],
                                             parent=self.personalGroup)
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor,
            FIF.PALETTE,
            self.tr('主题颜色'),
            self.tr('选择应用的主题色'),
            self.personalGroup,
            default_color=QColor("#ff5d74a2")
        )
        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.themeColorCard)

        # 添加设置组到布局
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.attendanceGroup)

        StyleSheet.SETTING_INTERFACE.apply(self)

        # 连接信号-槽
        self.themeCard.comboBox.currentIndexChanged.connect(lambda: setTheme(cfg.get(cfg.themeMode), lazy=True))
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c, lazy=True))
        self.loginMethodCard.comboBox.currentIndexChanged.connect(lambda: cfg.set(cfg.defaultAttendanceLoginMethod,
                                                                                  cfg.AttendanceLoginMethod(
                                                                                      self.loginMethodCard.comboBox.currentIndex())))
        self.encryptCard.clicked.connect(self.onEncryptAccountClicked)
        self.decryptCard.clicked.connect(self._onCancelEncryptClicked)

    @pyqtSlot()
    def onEncryptAccountClicked(self):
        if len(accounts) == 0:
            if accounts.encrypted:
                w = DecryptDialog(self)
                if not w.exec():
                    InfoBar.error(self.tr("修改密码失败"), self.tr("必须先解密账户才能修改密码"), duration=2000,
                                  parent=self)
                    return
            else:
                InfoBar.error(self.tr("加密失败"), self.tr("需要存在一个账户才可以加密"), duration=2000, parent=self)
                return

        w = EncryptDialog(self)
        w.exec()

    @pyqtSlot()
    def _onUpdateEncryptStatus(self):
        if accounts.encrypted:
            self.encryptCard.button.setText(self.tr("修改密码"))
            self.decryptCard.button.setEnabled(True)
            self.decryptCard.button.setText(self.tr("不再加密"))
        else:
            self.encryptCard.button.setText(self.tr("加密"))
            self.decryptCard.button.setEnabled(False)
            self.decryptCard.button.setText(self.tr("未加密"))

    @pyqtSlot()
    def _onCancelEncryptClicked(self):
        if accounts.encrypted and len(accounts) == 0:
            w = DecryptDialog(self)
            if not w.exec():
                InfoBar.error(self.tr("取消加密失败"), self.tr("必须先解密账户才能取消加密"), duration=2000,
                              parent=self)
                return

        w = MessageBox(self.tr("是否确认不再加密?"),
                       self.tr("取消加密后，你的账户信息将重新使用明文存储，存在泄漏风险"), self)
        w.yesButton.setText(self.tr("不再加密"))
        w.cancelButton.setText(self.tr("取消"))
        if w.exec():
            accounts.setEncrypted(False)
