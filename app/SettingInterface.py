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
        # 个性化组
        self.personalGroup = SettingCardGroup(self.tr("个性化"), self.view)
        self.themeCard = ComboBoxSettingCard(cfg.themeMode, FIF.BRUSH, self.tr("应用主题"),
                                             self.tr("调整应用程序的外观"),
                                             texts=["浅色", "深色", "自动"],
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

        StyleSheet.SETTING_INTERFACE.apply(self)

        # 连接信号-槽
        self.themeCard.comboBox.currentIndexChanged.connect(lambda: setTheme(cfg.get(cfg.themeMode), lazy=True))
        self.themeColorCard.colorChanged.connect(lambda c: setThemeColor(c, lazy=True))
