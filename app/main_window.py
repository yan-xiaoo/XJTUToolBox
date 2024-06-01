from traceback import format_exception
from types import TracebackType
from typing import Type
import sys

from PyQt5.QtCore import pyqtSlot, QUrl
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, NavigationBarPushButton, MessageBox
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import NavigationItemPosition, isDarkTheme

from .HomeInterface import HomeInterface
from .AccountInterface import AccountInterface
from .SettingInterface import SettingInterface
from .AttendanceInterface import AttendanceInterface
from .ToolBoxInterface import ToolBoxInterface
from .sub_interfaces import LoginInterface
from .sub_interfaces import AutoJudgeInterface
from .utils import cfg, accounts, MyFluentIcon


class MainWindow(MSFluentWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initWindow()
        self.initInterface()
        self.initNavigation()

        self.light_icon = QIcon("assets/icons/toolbox_light.png")
        self.dark_icon = QIcon("assets/icons/toolbox_dark.png")

        self.on_theme_changed()
        cfg.themeChanged.connect(self.on_theme_changed)

        sys.excepthook = self.catchExceptions

    def initWindow(self):
        self.setWindowTitle("仙交百宝箱")
        self.setMinimumSize(785, 600)

        self.show()

    def initInterface(self):
        self.home_interface = HomeInterface(self, self)
        self.login_interface = LoginInterface(self)
        self.attendance_interface = AttendanceInterface(self, self)
        self.account_interface = AccountInterface(accounts, self, self)
        self.setting_interface = SettingInterface(self)
        self.tool_box_interface = ToolBoxInterface(self, self)
        self.judge_interface = AutoJudgeInterface(self)

    def initNavigation(self):
        self.addSubInterface(self.home_interface, FIF.HOME, self.tr("主页"))
        self.addSubInterface(self.attendance_interface, MyFluentIcon.ATTENDANCE, self.tr("考勤"))
        self.addSubInterface(self.tool_box_interface, FIF.APPLICATION, self.tr("工具"))

        self.navigationInterface.addWidget("GitHub",
                                           NavigationBarPushButton(FIF.GITHUB, self.tr("GitHub"), isSelectable=False,
                                                                   parent=self),
                                           lambda: QDesktopServices.openUrl(
                                               QUrl("https://github.com/yan-xiaoo/XJTUToolbox")),
                                           NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.account_interface, FIF.EDUCATION, self.tr("账户"),
                             position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.setting_interface, FIF.SETTING, self.tr("设置"),
                             position=NavigationItemPosition.BOTTOM)

        # 添加评教界面作为工具箱界面的卡片
        card = self.tool_box_interface.addCard(self.judge_interface, FIF.BOOK_SHELF, self.tr("一键评教"),
                                               self.tr("轻松完成每学期的评教问卷"))
        card.setFixedSize(200, 180)

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
        tracebackString = "".join(format_exception(ty, value, _traceback))
        box = MessageBox(
            self.tr("程序发生未经处理的异常"),
            content=tracebackString,
            parent=self,
        )
        box.yesButton.setText(self.tr("复制到剪切板"))
        box.cancelButton.setText(self.tr("关闭"))
        box.yesSignal.connect(
            lambda: QApplication.clipboard().setText(tracebackString)
        )
        box.exec()
        return sys.__excepthook__(ty, value, _traceback)

    @pyqtSlot()
    def on_theme_changed(self):
        if isDarkTheme():
            self.setWindowIcon(self.dark_icon)
        else:
            self.setWindowIcon(self.light_icon)
