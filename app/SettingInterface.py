from qfluentwidgets import ScrollArea, ExpandLayout, SettingCardGroup, ComboBoxSettingCard, setTheme, \
     setThemeColor
from qfluentwidgets import FluentIcon as FIF
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QColor

from .utils.config import cfg
from .utils.style_sheet import StyleSheet
from .cards.custom_color_setting_card import CustomColorSettingCard


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

        # 添加设置组
        # 考勤设置组
        self.attendanceGroup = SettingCardGroup(self.tr("考勤"), self.view)
        self.loginMethodCard = ComboBoxSettingCard(cfg.defaultAttendanceLoginMethod, FIF.GLOBE,
                                                   self.tr("考勤默认连接方式"), self.tr("选择是否默认通过 WebVPN 连接考勤系统"),
                                                   texts=[self.tr("不设置"), self.tr("直接连接"), self.tr("WebVPN 连接")],
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
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.attendanceGroup)

        StyleSheet.SETTING_INTERFACE.apply(self)

        # 连接信号-槽
        self.themeCard.comboBox.currentIndexChanged.connect(lambda: setTheme(cfg.get(cfg.themeMode), lazy=True))
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c, lazy=True))
        self.loginMethodCard.comboBox.currentIndexChanged.connect(lambda: cfg.set(cfg.defaultAttendanceLoginMethod,
                                                                                  cfg.AttendanceLoginMethod(self.loginMethodCard.comboBox.currentIndex())))
