import os
import sys
import shlex

import keyring
import keyring.errors
from PyQt5.QtCore import pyqtSlot, QUrl, pyqtSignal
from qfluentwidgets import ScrollArea, ExpandLayout, SettingCardGroup, ComboBoxSettingCard, setTheme, \
    setThemeColor, PrimaryPushSettingCard, PushSettingCard, InfoBar, MessageBox, InfoBadgePosition, \
    InfoBadge, LineEdit, SwitchButton, IndicatorPosition, BodyLabel, HyperlinkLabel
from qfluentwidgets import FluentIcon as FIF
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtGui import QColor, QDesktopServices

from .cards.copyable_switch_card import CopyablePushSettingCard
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
from .cards.scheduled_notice_card import ScheduledNoticeCard
from .sub_interfaces.EncryptDialog import EncryptDialog, DecryptDialog


class NoticeSearchCard(ScheduledNoticeCard):
    """
    定时查询通知的设置卡片
    """
    def __init__(self, interface, parent=None):
        super().__init__(icon=FIF.HISTORY, title="定期查询通知", enable_config_item=cfg.noticeAutoSearch,
                         time_config_item=cfg.noticeSearchTime,
                         content="每天自动查询并推送新通知",
                         dialog_parent=interface,
                         parent=parent)


class ScoreSearchCard(ScheduledNoticeCard):
    """
    定时查询成绩的设置卡片
    """
    def __init__(self, interface, parent=None):
        super().__init__(icon=FIF.EDUCATION, title="定期查询成绩", enable_config_item=cfg.scoreAutoSearch,
                         time_config_item=cfg.scoreSearchTime,
                         content="自动查询当前账户成绩并推送",
                         dialog_parent=interface,
                         parent=parent)

        self._interface = interface

        # ===== 自定义命令 Hook UI =====
        self.hookEnableLabel = BodyLabel(self.tr("查询后执行自定义命令"), self)
        self.hookEnableButton = SwitchButton(self.tr("关"), self, IndicatorPosition.RIGHT)
        self.hookEnableButton.setOnText(self.tr("开"))

        self.hookProgramLabel = BodyLabel(self.tr("命令路径"), self)
        self.hookProgramEdit = LineEdit(self)
        self.hookProgramEdit.setPlaceholderText(self.tr("可执行文件路径"))
        self.hookProgramEdit.setClearButtonEnabled(True)

        self.hookArgsLabel = BodyLabel(self.tr("命令参数"), self)
        self.hookArgsEdit = LineEdit(self)
        self.hookArgsEdit.setMinimumWidth(500)
        self.hookArgsEdit.setPlaceholderText(self.tr("参数（空格分隔，可用引号），支持 ${payload} ${event} ${timestamp} ${nickname}"))
        self.hookArgsEdit.setClearButtonEnabled(True)

        self.hookTimeoutLabel = BodyLabel(self.tr("超时（秒）"), self)
        self.hookTimeoutEdit = LineEdit(self)
        self.hookTimeoutEdit.setPlaceholderText(self.tr("例如：15"))
        self.hookTimeoutEdit.setClearButtonEnabled(True)

        self.hookIncludeAllLabel = BodyLabel(self.tr("传出完整成绩"), self)
        self.hookIncludeAllButton = SwitchButton(self.tr("关"), self, IndicatorPosition.RIGHT)
        self.hookIncludeAllButton.setOnText(self.tr("开"))

        self.hookDocLabel = BodyLabel(self.tr("文档"), self)
        self.hookDocLink = HyperlinkLabel(QUrl("https://docs.xjtutoolbox.com/tutorial/scheduled-event.html"), self.tr("查看自定义命令文档"), self)

        # 添加到卡片（位于“立刻推送”行之后）
        self.add(self.hookEnableLabel, self.hookEnableButton)
        self.add(self.hookProgramLabel, self.hookProgramEdit)
        self.add(self.hookArgsLabel, self.hookArgsEdit)
        self.add(self.hookTimeoutLabel, self.hookTimeoutEdit)
        self.add(self.hookIncludeAllLabel, self.hookIncludeAllButton)

        # 在 UI 栏目下方添加文档链接
        self.add(self.hookDocLabel, self.hookDocLink)

        # 初始值
        self.hookEnableButton.setChecked(cfg.scoreHookEnable.value)
        self.hookProgramEdit.setText(cfg.scoreHookProgram.value)
        self.hookArgsEdit.setText(self._format_args(cfg.scoreHookArgs.value))
        self.hookTimeoutEdit.setText(str(cfg.scoreHookTimeoutSec.value))
        self.hookIncludeAllButton.setChecked(cfg.scoreHookIncludeFullScores.value)

        self._refreshHookControlsEnabled()

        # 配置项 -> UI
        cfg.scoreHookEnable.valueChanged.connect(lambda _: self.hookEnableButton.setChecked(cfg.scoreHookEnable.value))
        cfg.scoreHookProgram.valueChanged.connect(lambda _: self.hookProgramEdit.setText(cfg.scoreHookProgram.value))
        cfg.scoreHookArgs.valueChanged.connect(lambda _: self.hookArgsEdit.setText(self._format_args(cfg.scoreHookArgs.value)))
        cfg.scoreHookTimeoutSec.valueChanged.connect(lambda _: self.hookTimeoutEdit.setText(str(cfg.scoreHookTimeoutSec.value)))
        cfg.scoreHookIncludeFullScores.valueChanged.connect(lambda _: self.hookIncludeAllButton.setChecked(cfg.scoreHookIncludeFullScores.value))

        # UI -> 配置项
        self.hookEnableButton.checkedChanged.connect(self._onHookEnableChanged)
        self.hookProgramEdit.editingFinished.connect(self._onHookProgramEdited)
        self.hookArgsEdit.editingFinished.connect(self._onHookArgsEdited)
        self.hookTimeoutEdit.editingFinished.connect(lambda: self._onHookIntEdited(self.hookTimeoutEdit, cfg.scoreHookTimeoutSec, 1, 600))
        self.hookIncludeAllButton.checkedChanged.connect(self._onHookIncludeAllChanged)

    @staticmethod
    def _format_args(args: list) -> str:
        try:
            return shlex.join(args)
        except Exception:
            return " ".join(args) if isinstance(args, list) else ""

    def _refreshHookControlsEnabled(self):
        """
        根据整个自定义命令功能是否启用，刷新其他控件的可用状态
        """
        enabled = bool(cfg.scoreHookEnable.value)
        self.hookProgramEdit.setEnabled(enabled)
        self.hookArgsEdit.setEnabled(enabled)
        self.hookTimeoutEdit.setEnabled(enabled)
        self.hookIncludeAllButton.setEnabled(enabled)

    @pyqtSlot(bool)
    def _onHookEnableChanged(self, checked: bool):
        """
        修改自定义命令功能启用状态时触发
        """
        cfg.scoreHookEnable.value = checked
        self._refreshHookControlsEnabled()

    @pyqtSlot(bool)
    def _onHookIncludeAllChanged(self, checked: bool):
        """
        修改是否包含所有成绩时触发
        """
        cfg.scoreHookIncludeFullScores.value = checked

    @pyqtSlot()
    def _onHookProgramEdited(self):
        cfg.scoreHookProgram.value = self.hookProgramEdit.text().strip()

    @pyqtSlot()
    def _onHookArgsEdited(self):
        text = self.hookArgsEdit.text().strip()
        if not text:
            cfg.scoreHookArgs.value = []
            return
        try:
            cfg.scoreHookArgs.value = shlex.split(text)
        except ValueError as e:
            InfoBar.error(self.tr("参数格式错误"), str(e), parent=self._interface)
            # 恢复为当前配置值
            self.hookArgsEdit.setText(self._format_args(cfg.scoreHookArgs.value))

    def _onHookIntEdited(self, edit: LineEdit, item, minimum: int, maximum: int):
        text = edit.text().strip()
        if not text:
            # 为空时恢复当前值
            edit.setText(str(item.value))
            return
        try:
            value = int(text)
        except ValueError:
            InfoBar.error(self.tr("数值格式错误"), self.tr("请输入整数"), parent=self._interface)
            edit.setText(str(item.value))
            return

        if value < minimum or value > maximum:
            InfoBar.error(self.tr("数值范围错误"), self.tr(f"请输入 {minimum} - {maximum} 之间的整数"), parent=self._interface)
            edit.setText(str(item.value))
            return
        item.value = value


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
        self.useReportCard = CustomSwitchSettingCard(FIF.VIEW, self.tr("未评教时查询成绩"), self.tr("查询成绩时，尝试通过请求成绩单绕过评教限制。"
                                                                                                 "可能导致查询时间增加"),
                                                    cfg.useScoreReport, self.scoreGroup)
        self.scoreGroup.addSettingCard(self.ignoreLateCard)
        self.scoreGroup.addSettingCard(self.useReportCard)

        # 通知查询组
        self.noticeGroup = SettingCardGroup(self.tr("定时查询"), self.view)
        self.noticeCard = NoticeSearchCard(self, self.view)
        self.scoreCard = ScoreSearchCard(self, self.view)
        self.noticeGroup.addSettingCard(self.noticeCard)
        self.noticeGroup.addSettingCard(self.scoreCard)

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
        self.visitorIdCard = CopyablePushSettingCard(
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
        self.visitorIdCard.copied.connect(self._onVisitorIdCopiedClicked)

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
            self.scoreCard.enableButton.setChecked(False)

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
    def _onVisitorIdCopiedClicked(self):
        QApplication.clipboard().setText(cfg.loginId.value)

    @pyqtSlot()
    def onUpdateClicked(self):
        if self.update_badge:
            self.update_badge.close()
            self.update_badge = None

        self.bar = InfoBar.info(self.tr("正在检查更新"), self.tr("正在检查更新，请稍后"), parent=self)
        self.bar.show()
        self.updateClicked.emit()
        checkUpdate(self)
