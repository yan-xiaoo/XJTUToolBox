import datetime
import os
import sys

import keyring
import keyring.errors
from PyQt5.QtCore import pyqtSlot, QUrl, pyqtSignal, QTime
from keyring.backends.SecretService import Keyring
from qfluentwidgets import ScrollArea, ExpandLayout, SettingCardGroup, ComboBoxSettingCard, setTheme, \
    setThemeColor, PrimaryPushSettingCard, PushSettingCard, InfoBar, MessageBox, InfoBadgePosition, \
    InfoBadge, ExpandGroupSettingCard, SwitchButton, IndicatorPosition, BodyLabel, TimePicker, PushButton
from qfluentwidgets import FluentIcon as FIF
from PyQt5.QtWidgets import QWidget, QHBoxLayout
from PyQt5.QtGui import QColor, QDesktopServices

from auth import generate_fp_visitor_id
from auth.util import old_fp_visitor_id
from .cards.custom_switch_card import CustomSwitchSettingCard
from .components.CustomMessageBox import ConfirmBox
from .sub_interfaces.ResetVisitorIdDialog import ResetVisitorIdDialog
from .threads.UpdateThread import checkUpdate, UpdateStatus
from .utils.account import KEYRING_SERVICE_NAME
from .utils.auto_start import add_to_startup, delete_from_startup
from .utils.config import cfg, TraySetting
from .utils import accounts, LOG_DIRECTORY, DEFAULT_ACCOUNT_PATH
from .utils.style_sheet import StyleSheet
from .cards.custom_color_setting_card import CustomColorSettingCard
from .sub_interfaces.EncryptDialog import EncryptDialog, DecryptDialog


class NoticeSearchCard(ExpandGroupSettingCard):
    """
    定时查询通知的设置卡片
    """
    def __init__(self, interface, parent=None):
        super().__init__(icon=FIF.HISTORY, title="定期查询通知", parent=parent)

        self.interface = interface
        self.card.setTitle(self.tr("定期查询通知"))
        self.card.setContent(self.tr("每天自动查询并推送新通知"))
        self.enableLabel = BodyLabel(self.tr("定期查询通知"), self)
        self.enableButton = SwitchButton(self.tr("关"), self, IndicatorPosition.RIGHT)
        self.enableButton.setOnText(self.tr("开"))

        self.timeLabel = BodyLabel(self.tr("查询时间"), self)
        self.timePicker = TimePicker(parent=self)
        self.timePicker.timeChanged.connect(self.onTimeChanged)
        time_ = cfg.noticeSearchTime.value
        self.timePicker.setTime(QTime(time_.hour, time_.minute))

        self.testLabel = BodyLabel(self.tr("立刻尝试推送通知"), self)
        self.testButton = PushButton(self.tr("立刻推送"), self)

        if not cfg.noticeAutoSearch.value:
            self.enableButton.setChecked(False)
            self.timePicker.setEnabled(False)
            self.testButton.setEnabled(False)
        else:
            self.enableButton.setChecked(True)
            self.timePicker.setEnabled(True)
            self.testButton.setEnabled(True)
        # 延迟链接
        self.enableButton.checkedChanged.connect(self.onEnableButtonClicked)

        self.add(self.enableLabel, self.enableButton)
        self.add(self.timeLabel, self.timePicker)
        self.add(self.testLabel, self.testButton)

    @pyqtSlot()
    def onEnableButtonClicked(self):
        if self.enableButton.isChecked():
            if cfg.traySetting.value != TraySetting.MINIMIZE:
                box = MessageBox(self.tr("开启定期查询"), self.tr("程序需要在后台运行以实现定时查询。\n是否允许程序常驻托盘？"),
                                 parent=self.interface)
                box.yesButton.setText(self.tr("确定"))
                box.cancelButton.setText(self.tr("取消"))
                if box.exec():
                    cfg.traySetting.value = TraySetting.MINIMIZE
                    self.timePicker.setEnabled(True)
                    cfg.noticeAutoSearch.value = True
                    self.testButton.setEnabled(True)
                else:
                    self.enableButton.setChecked(False)
                    self.timePicker.setEnabled(False)
                    cfg.noticeAutoSearch.value = False
                    self.testButton.setEnabled(False)
            else:
                self.timePicker.setEnabled(True)
                cfg.noticeAutoSearch.value = True
                self.testButton.setEnabled(True)
        else:
            self.timePicker.setEnabled(False)
            cfg.noticeAutoSearch.value = False
            self.testButton.setEnabled(False)

    @pyqtSlot(QTime)
    def onTimeChanged(self, time: QTime):
        """时间选择器的时间改变时触发"""
        cfg.noticeSearchTime.value = datetime.time(hour=time.hour(), minute=time.minute())

    def add(self, label, widget):
        w = QWidget()

        layout = QHBoxLayout(w)

        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(widget)

        # 添加组件到设置卡
        self.addGroupWidget(w)


class SettingInterface(ScrollArea):
    """设置界面"""
    # 当自身的「检查更新」按钮被点击时，发出此信号，用于消除主界面的提醒元素
    updateClicked = pyqtSignal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)

        self.setObjectName("SettingInterface")
        self.view = QWidget(self)
        self.view.setObjectName("scrollWidget")

        self.main_window = main_window

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
        self.clearCard = PushSettingCard(self.tr("清除"), FIF.CLEAR_SELECTION,
                                         self.tr("清除所有账户"), self.tr("清除本地存储的所有账户信息并撤销账户加密"))
        self.showAvatarCard = CustomSwitchSettingCard(
            FIF.EDUCATION,
            self.tr("显示当前账户头像"),
            self.tr("在侧边栏显示当前使用账户的头像"),
            cfg.showAvatarOnSideBar,
            self.accountGroup
        )
        self.saveKeyringCard = CustomSwitchSettingCard(
            FIF.VPN,
            self.tr("使用系统密码管理器"),
            self.tr("将账户密码存储在系统密码管理器中（如 macOS 钥匙串、Windows 凭据管理器）"),
            cfg.useKeyring,
            self.accountGroup
        )
        self.accountGroup.addSettingCard(self.encryptCard)
        self.accountGroup.addSettingCard(self.decryptCard)
        self.accountGroup.addSettingCard(self.clearCard)
        self.accountGroup.addSettingCard(self.showAvatarCard)
        self.accountGroup.addSettingCard(self.saveKeyringCard)

        self.saveKeyringCard.checkedChanged.connect(self._onSaveKeyringChanged)
        self._onUpdateEncryptStatus()

        # 考勤设置组
        self.attendanceGroup = SettingCardGroup(self.tr("考勤"), self.view)
        self.loginMethodCard = ComboBoxSettingCard(cfg.defaultAttendanceLoginMethod, FIF.GLOBE,
                                                   self.tr("考勤默认连接方式"),
                                                   self.tr("选择是否默认通过 WebVPN 连接考勤系统"),
                                                   texts=[self.tr("每次都询问"), self.tr("直接连接"),
                                                          self.tr("WebVPN 连接")],
                                                   parent=self.attendanceGroup)
        self.autoRetryCard = CustomSwitchSettingCard(FIF.ACCEPT, self.tr("自动重试查询"),
                                                     self.tr("在考勤系统查询失败时自动重试"), cfg.autoRetryAttendance, self.attendanceGroup)
        self.attendanceGroup.addSettingCard(self.loginMethodCard)
        self.attendanceGroup.addSettingCard(self.autoRetryCard)

        # 成绩查询组
        self.scoreGroup = SettingCardGroup(self.tr("成绩查询"), self.view)
        self.ignoreLateCard = CustomSwitchSettingCard(FIF.ERASE_TOOL, self.tr("忽略缓考课程"), self.tr("查询成绩时忽略缓考课程"),
                                                      cfg.ignoreLateCourse, self.scoreGroup)
        self.scoreGroup.addSettingCard(self.ignoreLateCard)

        # 通知查询组
        self.noticeGroup = SettingCardGroup(self.tr("通知查询"), self.view)
        self.noticeCard = NoticeSearchCard(self, self.view)
        self.noticeGroup.addSettingCard(self.noticeCard)

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

        # 关于组
        self.aboutGroup = SettingCardGroup(self.tr("关于"), self.view)

        self.minimizeToTrayCard = ComboBoxSettingCard(
            cfg.traySetting,
            FIF.MINIMIZE,
            self.tr("关闭程序时"),
            self.tr("点击关闭按钮时的行为"),
            texts=[self.tr("询问"), self.tr("直接退出"), self.tr("最小化到托盘")],
            parent=self.aboutGroup
        )
        self.autoStartCard = CustomSwitchSettingCard(
            FIF.POWER_BUTTON,
            self.tr("开机自启动"),
            self.tr("在开机时自动启动 XJTUToolbox"),
            cfg.autoStart,
            self.aboutGroup
        )
        self.updateOnStartCard = CustomSwitchSettingCard(
            FIF.UPDATE,
            self.tr("启动时检查更新"),
            self.tr("新版本将包含更多功能且更加稳定"),
            cfg.checkUpdateAtStartTime,
            self.aboutGroup
        )
        self.updateCard = PrimaryPushSettingCard(
            self.tr("检查更新"),
            FIF.INFO,
            self.tr("关于"),
            f"{self.tr('当前版本')} {cfg.version}",
        )
        self.prereleaseCard = CustomSwitchSettingCard(
            FIF.CLOUD,
            self.tr("获取预发布版本"),
            self.tr("更新到可用的预发布版本"),
            cfg.prereleaseEnable,
            self.aboutGroup
        )
        self.feedbackCard = PrimaryPushSettingCard(
            self.tr("提供反馈"),
            FIF.FEEDBACK,
            self.tr("提供反馈"),
            self.tr("通过提供反馈帮助我们改进 XJTUToolbox"),
            self.aboutGroup
        )
        self.logCard = PushSettingCard(
            self.tr("查看日志"),
            FIF.FOLDER,
            self.tr("查看日志"),
            self.tr("打开应用的日志目录"),
            self.aboutGroup
        )
        self.visitorIdCard = PushSettingCard(
            self.tr("重置 ID"),
            FIF.CONNECT,
            self.tr("客户端登录 ID"),
            str(cfg.loginId.value),
            self.aboutGroup
        )

        self.aboutGroup.addSettingCard(self.minimizeToTrayCard)
        self.aboutGroup.addSettingCard(self.feedbackCard)
        self.aboutGroup.addSettingCard(self.logCard)
        self.aboutGroup.addSettingCard(self.autoStartCard)
        self.aboutGroup.addSettingCard(self.updateOnStartCard)
        self.aboutGroup.addSettingCard(self.prereleaseCard)
        self.aboutGroup.addSettingCard(self.visitorIdCard)
        self.aboutGroup.addSettingCard(self.updateCard)

        # 添加设置组到布局
        self.expandLayout.addWidget(self.accountGroup)
        self.expandLayout.addWidget(self.attendanceGroup)
        self.expandLayout.addWidget(self.scoreGroup)
        self.expandLayout.addWidget(self.noticeGroup)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.aboutGroup)

        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(36, 15, 36, 15)

        StyleSheet.SETTING_INTERFACE.apply(self)
        # 更新小圆点
        self.update_badge = None

        # 连接信号-槽
        self.themeCard.comboBox.currentIndexChanged.connect(lambda: setTheme(cfg.get(cfg.themeMode), lazy=True))
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c, lazy=True))
        self.loginMethodCard.comboBox.currentIndexChanged.connect(lambda: cfg.set(cfg.defaultAttendanceLoginMethod,
                                                                                  cfg.AttendanceLoginMethod(
                                                                                      self.loginMethodCard.comboBox.currentIndex())))
        cfg.traySetting.valueChanged.connect(self._onTraySettingChanged)
        self.encryptCard.clicked.connect(self.onEncryptAccountClicked)
        self.decryptCard.clicked.connect(self._onCancelEncryptClicked)
        self.clearCard.clicked.connect(self._onClearAccountsClicked)
        self.updateCard.clicked.connect(self.onUpdateClicked)
        self.feedbackCard.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/yan-xiaoo/XJTUToolbox/issues")))
        self.logCard.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("file:///" + LOG_DIRECTORY)))
        self.autoStartCard.checkedChanged.connect(self._onAutoStartClicked)
        self.showAvatarCard.checkedChanged.connect(self._showAvatarClicked)
        self.visitorIdCard.clicked.connect(self._onVisitorIdClicked)

        if sys.platform == "darwin":
            # macOS 不支持直接设置自动启动
            cfg.autoStart.value = False
            self.autoStartCard.setSwitchEnabled(False)
            self.autoStartCard.showHint(self.tr("请前往设置-通用-登录项与扩展，在登录项中添加本程序，实现开机自启动"))
        if not getattr(sys, "frozen", False):
            # 非打包版本不支持自动启动
            self.autoStartCard.setVisible(False)
            self.aboutGroup.cardLayout.removeWidget(self.autoStartCard)
            self.aboutGroup.adjustSize()

    @pyqtSlot()
    def _onTraySettingChanged(self):
        if cfg.traySetting.value != TraySetting.MINIMIZE and cfg.noticeAutoSearch.value:
            cfg.noticeAutoSearch.value = False
            self.noticeCard.enableButton.setChecked(False)

    @pyqtSlot(bool)
    def _onAutoStartClicked(self, checked: bool):
        """自动启动设置被修改时触发"""
        if checked:
            add_to_startup()
        else:
            delete_from_startup()

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

    @pyqtSlot(bool)
    def _onSaveKeyringChanged(self, checked: bool):
        if not checked and not accounts.encrypted:
            box = MessageBox(self.tr("关闭系统密码管理器"), self.tr("关闭后，账户密码将以明文存储在数据文件中，可能会增加密码泄漏风险。\n是否确认关闭？"),
                             parent=self)
            box.yesButton.setText(self.tr("确认"))
            box.cancelButton.setText(self.tr("取消"))
            if box.exec():
                pass
            else:
                self.saveKeyringCard.setChecked(True)

        if cfg.useKeyring.value:
            if accounts.is_encrypted():
                with open(DEFAULT_ACCOUNT_PATH, "r") as f:
                    data = f.read()
                try:
                    keyring.set_password(KEYRING_SERVICE_NAME, "accounts", data)
                except keyring.errors.KeyringError:
                    InfoBar.error(self.tr(""), self.tr("错误：无法将账户保存到系统密码管理器中"), parent=self)
                    self.saveKeyringCard.setChecked(False)
            else:
                try:
                    accounts.save_to_keyring()
                except keyring.errors.KeyringError:
                    InfoBar.error(self.tr(""), self.tr("错误：无法将账户保存到系统密码管理器中"), parent=self)
                    self.saveKeyringCard.setChecked(False)
            try:
                os.remove(DEFAULT_ACCOUNT_PATH)
            except OSError:
                pass
        else:
            if accounts.is_encrypted():
                data = keyring.get_password(KEYRING_SERVICE_NAME, "accounts")
                if data:
                    with open(DEFAULT_ACCOUNT_PATH, "w") as f:
                        f.write(data)
            else:
                accounts.save_suitable()

            try:
                accounts.remove_from_keyring()
            except keyring.errors.KeyringError:
                pass


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
            accounts.setEncrypted(False, use_keyring=cfg.useKeyring.value)

    @pyqtSlot()
    def _onClearAccountsClicked(self):
        if accounts.encrypted:
            msg = self.tr("清除后，所有账户信息将被删除，且不可恢复。\n账户加密将同时被解除")
        else:
            msg = self.tr("清除后，所有账户信息将被删除，且不可恢复")
        w = ConfirmBox(self.tr("清除所有账户"), msg, self.tr("清除"), self.tr("请输入“清除”以确认"), self)
        w.yesButton.setText(self.tr("清除"))
        if w.exec():
            accounts.clear()
            InfoBar.success(title='', content="清除账户成功", parent=self)

    @pyqtSlot()
    def _showAvatarClicked(self):
        self.main_window.on_avatar_update()

    @pyqtSlot(UpdateStatus)
    def onUpdateCheck(self, status):
        if status == UpdateStatus.UPDATE_EXE_AVAILABLE or status == UpdateStatus.UPDATE_AVAILABLE:
            self.update_badge = InfoBadge.warning(1, parent=self.updateCard, target=self.updateCard.button,
                                                  position=InfoBadgePosition.TOP_RIGHT)

    @pyqtSlot()
    def _onVisitorIdClicked(self):
        w = ResetVisitorIdDialog(self)
        if w.exec():
            self.visitorIdCard.setContent(w.visitorId)
            cfg.loginId.value = w.visitorId
            InfoBar.success(self.tr("重置 ID 成功"), self.tr("新的客户端登录 ID 已经设置"), parent=self)

    @pyqtSlot()
    def onUpdateClicked(self):
        if self.update_badge:
            self.update_badge.close()
            self.update_badge = None

        self.bar = InfoBar.info(self.tr("正在检查更新"), self.tr("正在检查更新，请稍后"), parent=self)
        self.bar.show()
        self.updateClicked.emit()
        checkUpdate(self)
