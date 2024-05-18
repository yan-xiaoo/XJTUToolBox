import time

from PyQt5.QtCore import pyqtSlot, QUrl
from PyQt5.QtGui import QIcon, QDesktopServices
from qfluentwidgets import MSFluentWindow, NavigationBarPushButton
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import NavigationItemPosition, isDarkTheme

from .HomeInterface import HomeInterface
from .AccountInterface import AccountInterface
from .SettingInterface import SettingInterface
from .utils import cfg, accounts


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

    def initWindow(self):
        self.setWindowTitle("仙交百宝箱")
        self.setBaseSize(785, 600)

        self.show()

    def initInterface(self):
        self.home_interface = HomeInterface(self, self)
        self.account_interface = AccountInterface(accounts, self)
        self.setting_interface = SettingInterface(self)

    def initNavigation(self):
        self.addSubInterface(self.home_interface, FIF.HOME, self.tr("主页"))

        self.navigationInterface.addWidget("GitHub", NavigationBarPushButton(FIF.GITHUB, self.tr("GitHub"), isSelectable=False,
                                                                             parent=self),
                                           lambda: QDesktopServices.openUrl(QUrl("https://github.com/yan-xiaoo/XJTUToolbox")),
                                           NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.account_interface, FIF.EDUCATION, self.tr("账户"), position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.setting_interface, FIF.SETTING, self.tr("设置"), position=NavigationItemPosition.BOTTOM)

    @pyqtSlot()
    def on_theme_changed(self):
        if isDarkTheme():
            self.setWindowIcon(self.dark_icon)
        else:
            self.setWindowIcon(self.light_icon)
