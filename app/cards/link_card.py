# coding:utf-8
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import IconWidget, TextWrap, ScrollArea, isDarkTheme, FluentIconBase, FlowLayout
from ..utils.style_sheet import StyleSheet


class LinkCardColor:
    """ Link card color """
    __light_color_base = "QFrame{{background-color: rgba({0}, 0.95);}}"\
                         "QFrame:hover {{background-color: rgba({0}, 0.80);}}"\
                         "QLabel{{background-color:transparent;}}"\
                         "QLabel:hover{{background-color:transparent;}}"
    __dark_color_base = "QFrame{{background-color: rgba({0}, 0.80);}}"\
                        "QFrame:hover {{background-color: rgba({0}, 0.95);}}"\
                        "QLabel{{background-color:transparent;}}"\
                        "QLabel:hover{{background-color:transparent;}}"
    RED = 'red'
    LIGHT_BLUE = 'light_blue'
    LIGHT = "light"
    DARK = "dark"
    PURPLE = 'purple'
    YELLOW = 'yellow'
    BLUE = 'blue'
    GREEN = 'green'
    colors = {
        LIGHT_BLUE: {
            "light": __light_color_base.format("118, 162, 185"),
            "dark": __dark_color_base.format("118, 162, 185")
        },
        RED: {
            "light": __light_color_base.format("205, 68, 50"),
            "dark": __dark_color_base.format("205, 68, 50")
        },
        PURPLE: {
            "light": __light_color_base.format("139, 105, 158"),
            "dark": __dark_color_base.format("139, 105, 158")
        },
        YELLOW: {
            "light": __light_color_base.format("173, 139, 115"),
            "dark": __dark_color_base.format("173, 139, 115")
        },
        BLUE: {
            "light": __light_color_base.format("93, 116, 162"),
            "dark": __dark_color_base.format("93, 116, 162")
        },
        GREEN: {
            "light": __light_color_base.format("105, 169, 78"),
            "dark": __dark_color_base.format("105, 169, 78")
        }
    }


class LinkCard(QFrame):
    cardClicked = pyqtSignal()
    LinkCardColor = LinkCardColor

    def __init__(self, icon: str | FluentIconBase | QIcon, title, content, parent=None):
        super().__init__(parent=parent)
        self.setFixedSize(198, 180)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)

        self.__initWidget()

    def __initWidget(self):
        self.setCursor(Qt.PointingHandCursor)

        self.iconWidget.setFixedSize(54, 54)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(24, 24, 0, 13)
        self.vBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addSpacing(16)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

    def setBackgroundColor(self, color: LinkCardColor):
        """ set background palette """
        if color not in LinkCardColor.colors:
            return
        self.setStyleSheet(LinkCardColor.colors[color][LinkCardColor.DARK if isDarkTheme() else LinkCardColor.LIGHT])

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.cardClicked.emit()


class LinkCardView(ScrollArea):
    """ Link card view """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.flowLayout = FlowLayout(self.view)

        self.flowLayout.setContentsMargins(66, 0, 0, 0)
        self.flowLayout.setSpacing(12)
        self.flowLayout.setAlignment(Qt.AlignLeft)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setObjectName('view')
        StyleSheet.LINK_CARD.apply(self)

    def addCard(self, card: LinkCard):
        """ add link card """
        self.flowLayout.addWidget(card)
