# coding:utf-8
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData, QPoint
from PyQt5.QtGui import QIcon, QDrag, QPainter, QPixmap
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import IconWidget, TextWrap, ScrollArea, isDarkTheme, FluentIconBase, FlowLayout, FluentIcon, ToolButton
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
    ORANGE = 'orange'
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
            "light": __light_color_base.format("101, 136, 115"),
            "dark": __dark_color_base.format("101, 136, 115")
        },
        ORANGE: {
            "light": __light_color_base.format("220, 135, 90"),
            "dark": __dark_color_base.format("235, 145, 99")
        }
    }


class LinkCard(QFrame):
    cardClicked = pyqtSignal()
    cardDeleted = pyqtSignal()
    LinkCardColor = LinkCardColor

    def __init__(self, icon: str | FluentIconBase | QIcon, title, content, parent=None, card_id=None):
        super().__init__(parent=parent)
        self.card_id = card_id or title  # 唯一标识符
        self.setFixedSize(198, 180)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)

        # 编辑模式相关
        self._edit_mode = False
        self._drag_start_position = QPoint()

        # 删除按钮
        self.deleteButton = ToolButton(FluentIcon.CLOSE, self)
        self.deleteButton.setFixedSize(24, 24)
        self.deleteButton.clicked.connect(self.cardDeleted.emit)
        self.deleteButton.hide()

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

        # 位置删除按钮在右上角
        self.deleteButton.move(self.width() - 30, 6)

    def setBackgroundColor(self, color: LinkCardColor):
        """ set background palette """
        if color not in LinkCardColor.colors:
            return
        self.setStyleSheet(LinkCardColor.colors[color][LinkCardColor.DARK if isDarkTheme() else LinkCardColor.LIGHT])

    def setEditMode(self, edit_mode: bool):
        """设置编辑模式"""
        self._edit_mode = edit_mode
        if edit_mode:
            self.setCursor(Qt.OpenHandCursor)
            self.deleteButton.show()
        else:
            self.setCursor(Qt.PointingHandCursor)
            self.deleteButton.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_position = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return

        if not self._edit_mode:
            return

        # 开始拖拽
        drag = QDrag(self)
        mimeData = QMimeData()
        mimeData.setText(self.card_id)  # 传递卡片ID
        drag.setMimeData(mimeData)

        # 创建拖拽时的预览图
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(0.7)
        self.render(painter)
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._drag_start_position)

        # 执行拖拽
        self.setCursor(Qt.ClosedHandCursor)
        drag.exec_(Qt.MoveAction)
        self.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if not self._edit_mode:  # 只有非编辑模式才触发点击事件
            self.cardClicked.emit()


class LinkCardView(ScrollArea):
    """ Link card view """
    cardOrderChanged = pyqtSignal(list)  # 发出卡片顺序变化信号
    cardDeleted = pyqtSignal(str)  # 发出卡片删除信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.flowLayout = FlowLayout(self.view)

        self.flowLayout.setContentsMargins(66, 0, 0, 0)
        self.flowLayout.setSpacing(12)
        self.flowLayout.setAlignment(Qt.AlignLeft)
        self.setMinimumHeight(370)

        # 编辑模式相关
        self._edit_mode = False
        self._cards = []  # 维护卡片列表
        self._available_cards = {}  # 所有可用的卡片定义

        # 启用拖放
        self.setAcceptDrops(True)
        self.view.setAcceptDrops(True)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setObjectName('view')
        StyleSheet.LINK_CARD.apply(self)

    def setAvailableCards(self, available_cards: dict):
        """设置所有可用的卡片定义
        available_cards 格式: {card_id: {'icon': icon, 'title': title, 'content': content, 'callback': callback}}
        """
        self._available_cards = available_cards

    def addCard(self, card: LinkCard):
        """ add link card """
        self.flowLayout.addWidget(card)
        self._cards.append(card)
        card.cardDeleted.connect(lambda: self._onCardDeleted(card))
        # 新添加的卡片应该继承当前的编辑模式状态
        card.setEditMode(self._edit_mode)

    def removeCard(self, card: LinkCard):
        """移除卡片"""
        if card in self._cards:
            self.flowLayout.removeWidget(card)
            self._cards.remove(card)
            self.flowLayout.update()
            card.deleteLater()

    def setEditMode(self, edit_mode: bool):
        """设置编辑模式"""
        self._edit_mode = edit_mode
        for card in self._cards:
            card.setEditMode(edit_mode)

    def _onCardDeleted(self, card: LinkCard):
        """处理卡片删除"""
        self.removeCard(card)
        self.cardDeleted.emit(card.card_id)
        self._updateCardOrder()

    def getCardOrder(self):
        """获取当前卡片顺序"""
        return [card.card_id for card in self._cards]

    def setCardOrder(self, card_ids: list):
        """设置卡片顺序"""
        # 先移除所有卡片但不删除
        for card in self._cards[:]:
            self.flowLayout.removeWidget(card)

        # 按新顺序重新添加
        new_cards = []
        for card_id in card_ids:
            for card in self._cards:
                if card.card_id == card_id:
                    self.flowLayout.addWidget(card)
                    new_cards.append(card)
                    break

        self._cards = new_cards

    def addCardById(self, card_id: str):
        """通过ID添加卡片"""
        if card_id not in self._available_cards:
            return False

        # 检查是否已存在
        for card in self._cards:
            if card.card_id == card_id:
                return False

        card_def = self._available_cards[card_id]
        card = LinkCard(
            card_def['icon'],
            card_def['title'],
            card_def['content'],
            parent=self,
            card_id=card_id
        )

        # 连接点击信号
        if 'callback' in card_def:
            card.cardClicked.connect(card_def['callback'])

        self.addCard(card)
        self._updateCardOrder()
        return True

    def _updateCardOrder(self):
        """更新卡片顺序并发出信号"""
        order = self.getCardOrder()
        self.cardOrderChanged.emit(order)

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasText() and self._edit_mode:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """拖拽移动事件"""
        if event.mimeData().hasText() and self._edit_mode:
            event.acceptProposedAction()

    def dropEvent(self, event):
        """拖拽放下事件"""
        if not self._edit_mode:
            return

        card_id = event.mimeData().text()
        drop_position = event.pos()

        # 找到被拖拽的卡片
        dragged_card = None
        for card in self._cards:
            if card.card_id == card_id:
                dragged_card = card
                break

        if not dragged_card:
            return

        # 计算插入位置
        insert_index = self._calculateInsertIndex(drop_position)

        # 重新排列卡片
        self._rearrangeCards(dragged_card, insert_index)

        event.acceptProposedAction()
        self._updateCardOrder()

    def _calculateInsertIndex(self, drop_position):
        """计算插入位置"""
        # 将ScrollArea坐标转换为view的本地坐标
        view_position = self.mapToGlobal(drop_position)
        view_position = self.view.mapFromGlobal(view_position)

        # 找到最接近的卡片位置
        min_distance = float('inf')
        insert_index = len(self._cards)

        for i, card in enumerate(self._cards):
            card_center = card.geometry().center()
            distance = (card_center - view_position).manhattanLength()

            if distance < min_distance:
                min_distance = distance
                # 根据拖拽位置决定插入到卡片前还是后
                if view_position.x() < card_center.x():
                    insert_index = i
                else:
                    insert_index = i + 1

        return insert_index

    def _rearrangeCards(self, dragged_card, insert_index):
        """重新排列卡片"""
        # 获取当前卡片的索引
        current_index = self._cards.index(dragged_card)

        # 如果插入位置和当前位置相同，不需要移动
        if current_index == insert_index or (current_index == insert_index - 1):
            return

        # 先从布局中移除被拖拽的卡片
        self.flowLayout.removeWidget(dragged_card)

        # 从列表中移除被拖拽的卡片
        self._cards.pop(current_index)

        # 调整插入索引
        if current_index < insert_index:
            insert_index -= 1

        # 插入到新位置
        self._cards.insert(insert_index, dragged_card)

        # 重新构建整个布局
        self._rebuildLayout()

    def _rebuildLayout(self):
        """重新构建布局"""
        # 清空当前布局
        for card in self._cards:
            self.flowLayout.removeWidget(card)

        # 重新添加所有卡片到布局
        for card in self._cards:
            self.flowLayout.addWidget(card)
        self.flowLayout.update()

    def getAvailableCardsForAddition(self):
        """获取可以添加的卡片列表"""
        current_ids = {card.card_id for card in self._cards}
        available = {}

        for card_id, card_def in self._available_cards.items():
            if card_id not in current_ids:
                available[card_id] = card_def

        return available
