from PyQt5.QtWidgets import QWidget
from qfluentwidgets import ScrollArea, FlowLayout
from .cards.tool_card import ToolCard
from .utils import StyleSheet


class ToolBoxInterface(ScrollArea):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)

        self.main_window = main_window

        self.setObjectName("toolBoxInterface")
        self.view = QWidget(self)
        self.view.setObjectName("view")

        self.flowLayout = FlowLayout(self.view)
        self.flowLayout.setContentsMargins(24, 24, 24, 24)
        self.flowLayout.setHorizontalSpacing(12)
        self.flowLayout.setVerticalSpacing(12)

        self.cards = []

        StyleSheet.TOOLBOX_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def addCard(self, interface, icon, title, content):
        """
        添加一张卡片。点击这张卡片后，会跳转到 interface。
        此方法在主界面中将 interface 注册为一个不可见的子界面，以便实现跳转。
        :param interface: 任何组件，必须设置了名称
        :param icon: 图标，会显示在卡片中
        :param title: 卡片的标题
        :param content: 卡片的内容
        """
        button = self.main_window.addSubInterface(interface, icon, "")
        button.setVisible(False)

        card = ToolCard(icon, title, content, self.view)
        card.cardClicked.connect(lambda: self.main_window.switchTo(interface))
        self.flowLayout.addWidget(card)
        self.cards.append(card)
        return card
