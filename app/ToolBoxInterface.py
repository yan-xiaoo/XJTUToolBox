from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QGridLayout, QLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ScrollArea, SearchLineEdit, SubtitleLabel, TitleLabel

from .cards.tool_card import ToolCard
from .utils import StyleSheet

if TYPE_CHECKING:
    from .components.feature_navigation import Feature
    from .main_window import MainWindow


class ToolCardGrid(QWidget):
    """按卡片数量和宽度计算高度，不依赖祖先页面是否可见。"""

    def __init__(self, parent: QWidget) -> None:
        """创建使用原生布局管理的自适应卡片网格。"""
        super().__init__(parent)
        self.gridLayout = QGridLayout(self)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setHorizontalSpacing(12)
        self.gridLayout.setVerticalSpacing(12)
        self.gridLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # 旧列数的布局最小宽度不能锁住容器，否则缩窗不会触发更少列的重排。
        self.gridLayout.setSizeConstraint(QLayout.SetNoConstraint)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._cards: tuple[ToolCard, ...] = ()
        self._columns = 0
        self.setFixedHeight(0)

    def clearCards(self) -> None:
        """先移出并隐藏旧卡片，供所有分组清空后统一重新分配。"""
        while self.gridLayout.count():
            item = self.gridLayout.takeAt(0)
            card = item.widget()
            if card is not None:
                card.hide()
        self._cards = ()
        self._columns = 0
        self.setFixedHeight(0)

    def setCards(self, cards: tuple[ToolCard, ...]) -> None:
        """接收当前筛选结果中的卡片，恢复显示并更新网格尺寸。"""
        self._cards = cards
        self._columns = 0
        self._reflow()
        for card in cards:
            card.show()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """宽度变化时重排列数，随即向外层提供正确内容高度。"""
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """仅按明确的卡片尺寸计算布局，隐藏时也能正确计算。"""
        if not self._cards:
            return
        spacing = self.gridLayout.horizontalSpacing()
        cardWidth = self._cards[0].width()
        self.setMinimumWidth(cardWidth)
        columns = max(1, (self.contentsRect().width() + spacing) // (cardWidth + spacing))
        if columns == self._columns:
            return
        self._columns = columns
        while self.gridLayout.count():
            self.gridLayout.takeAt(0)
        for index, card in enumerate(self._cards):
            self.gridLayout.addWidget(card, index // columns, index % columns)
        rows = (len(self._cards) + columns - 1) // columns
        height = rows * self._cards[0].height() + (rows - 1) * self.gridLayout.verticalSpacing()
        self.setFixedHeight(height)
        self.gridLayout.invalidate()
        self.updateGeometry()


class ToolBoxInterface(ScrollArea):
    """提供全部功能搜索，并将已固定到侧栏的功能放在下方。"""

    featureOpened = pyqtSignal(str)
    pinToggled = pyqtSignal(str)

    def __init__(self, main_window: MainWindow, parent: QWidget | None = None) -> None:
        """构造工具箱标题、搜索框和分组容器。"""
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("toolBoxInterface")
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.contentLayout = QVBoxLayout(self.view)
        self.contentLayout.setContentsMargins(24, 24, 24, 24)
        self.contentLayout.setSpacing(16)
        self.contentLayout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.contentLayout.addWidget(TitleLabel(self.tr("工具箱"), self.view))
        self.searchEdit = SearchLineEdit(self.view)
        self.searchEdit.setPlaceholderText(self.tr("搜索功能名称或说明"))
        self.contentLayout.addWidget(self.searchEdit)
        self.emptyLabel = BodyLabel(self.tr("没有匹配的功能，请尝试其他关键词"), self.view)
        self.contentLayout.addWidget(self.emptyLabel)
        self.emptyLabel.hide()
        self.features: tuple[Feature, ...] = ()
        self.cards: dict[str, ToolCard] = {}
        self.sections: dict[bool, QWidget] = {}
        self.groups: dict[tuple[bool, str], tuple[QWidget, ToolCardGrid]] = {}
        self._pinned: set[str] = set()
        self._scrollRestore = QTimer(self)
        self._scrollRestore.setSingleShot(True)
        self._scrollRestore.timeout.connect(self._restoreScroll)
        self._scrollPosition = 0
        StyleSheet.TOOLBOX_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.searchEdit.textChanged.connect(self._refreshCards)

    def setFeatures(self, features: tuple[Feature, ...]) -> None:
        """用统一功能清单创建卡片，不注册或重新创建业务页面。"""
        self.features = features
        categories = tuple(dict.fromkeys(feature.category for feature in features))
        for pinned, title in ((False, self.tr("其他功能")), (True, self.tr("已固定到侧栏"))):
            section = QWidget(self.view)
            sectionLayout = QVBoxLayout(section)
            sectionLayout.setContentsMargins(0, 0, 0, 0)
            sectionLayout.setSpacing(12)
            sectionLayout.addWidget(SubtitleLabel(title, section))
            for category in categories:
                group = QWidget(section)
                groupLayout = QVBoxLayout(group)
                groupLayout.setContentsMargins(0, 0, 0, 0)
                groupLayout.addWidget(BodyLabel(category, group))
                grid = ToolCardGrid(group)
                groupLayout.addWidget(grid)
                sectionLayout.addWidget(group)
                self.groups[pinned, category] = group, grid
            self.contentLayout.addWidget(section)
            self.sections[pinned] = section
        self.contentLayout.addStretch()
        for feature in features:
            card = ToolCard(feature.icon, feature.title, feature.description, self.view)
            card.cardClicked.connect(partial(self.featureOpened.emit, feature.key))
            card.pinClicked.connect(partial(self.pinToggled.emit, feature.key))
            self.cards[feature.key] = card
        self._refreshCards()

    def setPinnedFeatures(self, pinned: set[str]) -> None:
        """同步固定状态，并在卡片换区后尽量保留滚动位置。"""
        self._scrollPosition = self.verticalScrollBar().value()
        self._pinned = pinned.copy()
        self._refreshCards()
        self._scrollRestore.start(0)

    def _restoreScroll(self) -> None:
        """布局更新后恢复滚动位置，由滚动条自动限制有效范围。"""
        self.verticalScrollBar().setValue(self._scrollPosition)

    def _refreshCards(self, text: str = "") -> None:
        """按固定状态分区，再按清单中的类别和默认顺序排列。"""
        query = self.searchEdit.text().strip().casefold()
        # 先清空全部分组，避免后处理的旧分组再次隐藏已移动到新分组的卡片。
        for _, grid in self.groups.values():
            grid.clearCards()
        grouped: dict[tuple[bool, str], list[ToolCard]] = {key: [] for key in self.groups}
        for feature in self.features:
            card = self.cards[feature.key]
            pinned = feature.key in self._pinned
            card.setPinned(pinned)
            groupKey = pinned, feature.category
            matches = query in f"{feature.title} {feature.description} {feature.category}".casefold()
            if matches:
                grouped[groupKey].append(card)
        visibleGroups = {key for key, cards in grouped.items() if cards}
        for groupKey, (group, grid) in self.groups.items():
            grid.setCards(tuple(grouped[groupKey]))
            group.setVisible(groupKey in visibleGroups)
        for pinned, section in self.sections.items():
            section.setVisible(any(key[0] == pinned for key in visibleGroups))
        self.emptyLabel.setVisible(not visibleGroups)
