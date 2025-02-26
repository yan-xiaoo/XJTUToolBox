import platform
from traceback import format_exception
from types import TracebackType
from typing import Type
import sys

from PyQt5.QtCore import pyqtSlot, QUrl, Qt
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, NavigationBarPushButton, MessageBox, InfoBadgePosition, \
    InfoBadge
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import NavigationItemPosition, isDarkTheme

from .HomeInterface import HomeInterface
from .AccountInterface import AccountInterface
from .ScheduleInterface import ScheduleInterface
from .ScoreInterface import ScoreInterface
from .SettingInterface import SettingInterface
from .AttendanceInterface import AttendanceInterface
from .ToolBoxInterface import ToolBoxInterface
from .sessions.attendance_session import AttendanceSession
from .sessions.ehall_session import EhallSession
from .sessions.jwapp_session import JwappSession
from .sub_interfaces import LoginInterface
from .sub_interfaces import AutoJudgeInterface
from .sub_interfaces.WebVPNConvertInterface import WebVPNConvertInterface
from .threads.UpdateThread import UpdateThread, UpdateStatus
from .utils import cfg, accounts, MyFluentIcon, SessionManager, logger, migrate_all


def registerSession():
    """
    注册各个子网站需要使用的 Session 类
    """
    # ehall：ehall.xjtu.edu.cn 所用的 session
    SessionManager.global_register(EhallSession, "ehall")
    SessionManager.global_register(AttendanceSession, "attendance")
    SessionManager.global_register(JwappSession, "jwapp")


class MainWindow(MSFluentWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        registerSession()
        self.initWindow()
        self.initInterface()
        self.initNavigation()

        self.light_icon = QIcon("assets/icons/toolbox_light.png")
        self.dark_icon = QIcon("assets/icons/toolbox_dark.png")

        self.on_theme_changed()
        cfg.themeChanged.connect(self.on_theme_changed)

        sys.excepthook = self.catchExceptions
        self.setting_badge = None

        if migrate_all():
            box = MessageBox("需要重启",
                             "数据目录迁移完成，目前程序无法获取任何账户数据，需要重启程序才能生效",
                             parent=self)
            box.yesButton.setText(self.tr("重启"))
            box.cancelButton.setText(self.tr("关闭"))
            box.yesSignal.connect(lambda: sys.exit(0))
            box.exec()

        self.setting_interface.updateClicked.connect(self.on_setting_button_clicked)
        if cfg.checkUpdateAtStartTime.value:
            self.update_thread = UpdateThread()
            self.update_thread.updateSignal.connect(self.on_update_check)
            self.update_thread.updateSignal.connect(self.setting_interface.onUpdateCheck)
            self.update_thread.start()

    def initWindow(self):
        self.setWindowTitle("仙交百宝箱")
        self.setMinimumSize(900, 671)

        self.show()

    def initInterface(self):
        self.home_interface = HomeInterface(self, self)
        self.login_interface = LoginInterface(self)
        self.attendance_interface = AttendanceInterface(self, self)
        self.account_interface = AccountInterface(accounts, self, self)
        self.setting_interface = SettingInterface(self)
        self.tool_box_interface = ToolBoxInterface(self, self)
        self.schedule_interface = ScheduleInterface(self)
        self.score_interface = ScoreInterface(self)
        self.judge_interface = AutoJudgeInterface(self)
        self.webvpn_convert_interface = WebVPNConvertInterface(self)

    def initNavigation(self):
        self.addSubInterface(self.home_interface, FIF.HOME, self.tr("主页"))
        self.addSubInterface(self.schedule_interface, FIF.CALENDAR, self.tr("课表"))
        self.addSubInterface(self.attendance_interface, MyFluentIcon.ATTENDANCE, self.tr("考勤"))
        self.addSubInterface(self.score_interface, FIF.EDUCATION, self.tr("成绩"))
        self.addSubInterface(self.tool_box_interface, FIF.APPLICATION, self.tr("工具"))

        self.navigationInterface.addWidget("GitHub",
                                           NavigationBarPushButton(FIF.GITHUB, self.tr("GitHub"), isSelectable=False,
                                                                   parent=self),
                                           lambda: QDesktopServices.openUrl(
                                               QUrl("https://github.com/yan-xiaoo/XJTUToolbox")),
                                           NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.account_interface, FIF.EDUCATION, self.tr("账户"),
                             position=NavigationItemPosition.BOTTOM)
        self.settingButton = self.addSubInterface(self.setting_interface, FIF.SETTING, self.tr("设置"),
                                                  position=NavigationItemPosition.BOTTOM)

        # 添加评教界面作为工具箱界面的卡片
        card = self.tool_box_interface.addCard(self.judge_interface, FIF.BOOK_SHELF, self.tr("一键评教"),
                                               self.tr("轻松完成每学期的评教问卷"))
        card.setFixedSize(200, 180)

        webvpn_card = self.tool_box_interface.addCard(self.webvpn_convert_interface, FIF.GLOBE, self.tr("WebVPN 网址转换"),
                                                      self.tr("将 WebVPN 网址转换为可直接访问的网址"))
        webvpn_card.setFixedSize(210, 180)

        # 添加登录界面作为子界面，但是将其隐藏
        button = self.addSubInterface(self.login_interface, FIF.SCROLL, self.tr("登录"),
                                      position=NavigationItemPosition.BOTTOM)
        button.setVisible(False)

    def catchExceptions(self, ty: Type[BaseException], value: BaseException, _traceback: TracebackType):
        """
        全局捕获异常，并弹窗显示
        :param ty: 异常的类型
        :param value: 异常的对象
        :param _traceback: 异常的traceback
        """
        logger.error("未经处理的异常", exc_info=(ty, value, _traceback))
        tracebackString = "".join(format_exception(ty, value, _traceback))
        box = MessageBox(
            self.tr("程序发生未经处理的异常"),
            content=tracebackString,
            parent=self,
        )
        # 允许错误内容被复制
        box.contentLabel.setTextInteractionFlags(box.contentLabel.textInteractionFlags() | Qt.TextSelectableByMouse)
        box.yesButton.setText(self.tr("复制到剪切板"))
        box.cancelButton.setText(self.tr("关闭"))
        box.yesSignal.connect(
            lambda: QApplication.clipboard().setText(tracebackString)
        )
        box.setClosableOnMaskClicked(True)
        box.exec()
        return sys.__excepthook__(ty, value, _traceback)

    @pyqtSlot()
    def on_theme_changed(self):
        if platform.system() == "Darwin":
            if isDarkTheme():
                self.setWindowIcon(self.dark_icon)
            else:
                self.setWindowIcon(self.light_icon)
        else:
            self.setWindowIcon(QIcon("assets/icons/main_icon.ico"))

    @pyqtSlot(UpdateStatus)
    def on_update_check(self, status: UpdateStatus):
        if status == UpdateStatus.UPDATE_EXE_AVAILABLE or status == UpdateStatus.UPDATE_AVAILABLE:
            self.setting_badge = InfoBadge.warning(1, parent=self.settingButton.parent(),
                                                   target=self.settingButton, position=InfoBadgePosition.NAVIGATION_ITEM)

    @pyqtSlot()
    def on_setting_button_clicked(self):
        if self.setting_badge:
            self.setting_badge.close()
