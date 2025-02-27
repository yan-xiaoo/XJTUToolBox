from PyQt5.QtCore import pyqtSignal, Qt, QPoint
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import QHBoxLayout, QWidget, QGraphicsOpacityEffect, QFrame, QListWidgetItem
from qfluentwidgets import LineEditButton, CheckBox, MenuAnimationType, TransparentToolButton, LineEdit, \
    BodyLabel, isDarkTheme, ListView, ListWidget, ScrollArea
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.components.widgets.combo_box import ComboBoxBase


class SelectionTag(QWidget):
    """
    小的标签，用于显示当前已经在 ComboBox 中选中的内容，并且可以点击删除
    """
    # 点击删除按钮后发出的信号
    deleteClicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)

        self.label = BodyLabel(text, self)
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.opacity.setOpacity(0.8)

        self.deleteButton = TransparentToolButton(FIF.CLOSE, self)
        self.deleteButton.setFixedSize(10, 10)
        self.deleteButton.clicked.connect(self.deleteClicked.emit)

        self.hBoxLayout.addWidget(self.label)
        self.hBoxLayout.addSpacing(5)
        self.hBoxLayout.addWidget(self.deleteButton, 0, alignment=Qt.AlignVCenter | Qt.AlignRight)
        self.hBoxLayout.setSpacing(0)

        self.adjustSize()
        self.setFixedWidth(self.width())
        self.setFixedHeight(20)

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        painter.setBrush(QColor(255, 255, 255, 50) if isDarkTheme() else QColor(0, 0, 0, 50))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())


class MultiSelectionComboBox(LineEdit, ComboBoxBase):
    """可多选的 ComboBox"""

    currentIndexChanged = pyqtSignal(int)
    currentTextChanged = pyqtSignal(str)

    def __init__(self, all_select_option=False, parent=None):
        """
        创建一个可多选的 ComboBox
        :param all_select_option: 是否显示一个全选的选项
        :param parent: 父组件
        """
        super().__init__(parent=parent)
        self.setReadOnly(True)
        self.dropButton = LineEditButton(FIF.ARROW_DOWN, self)

        self.show_all_select_option = all_select_option

        self.dropButton.setFixedSize(30, 25)
        self.internalFrame = ScrollArea(self)
        self.internalFrame.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.internalWidget = QWidget(self.internalFrame)

        self.internalFrame.setStyleSheet("QScrollArea {border: none;background-color: transparent;}")
        self.internalWidget.setStyleSheet("background-color: transparent;")

        self.internalLayout = QHBoxLayout(self.internalWidget)
        self.internalLayout.setContentsMargins(5, 3, 3, 5)
        self.internalLayout.setSpacing(5)

        self.setFixedHeight(40)

        # 已选中的项目的索引序号
        self.selected = set()
        # 已选中的索引对应的 tag
        self.selected_tags = {}
        # 所有的选项框。仅在菜单展开时，选项框列表不是 None。列表中不包含「全选」选项框。
        self.check_boxes = None
        # 所有的选项框，包含「全选」选项框
        self.all_check_boxes = None

        self.dropButton.clicked.connect(self._toggleComboMenu)

        self.internalFrame.setWidget(self.internalWidget)
        self.internalFrame.setWidgetResizable(True)

        self.hBoxLayout.addWidget(self.internalFrame, stretch=1, alignment=Qt.AlignLeft)
        self.hBoxLayout.addWidget(self.dropButton, 0, Qt.AlignRight)

    def mouseReleaseEvent(self, a0):
        self._toggleComboMenu()

    def selectedIndex(self):
        return sorted(tuple(self.selected))

    def allSelected(self) -> bool:
        return len(self.selected) == len(self.items)

    def addSelectIndex(self, index: int):
        if index >= self.count() or index < 0 or index in self.selected:
            return

        self.selected.add(index)
        self.generateTags()

    def addSelectIndexes(self, indexes: list):
        for index in indexes:
            if index >= self.count() or index < 0 or index in self.selected:
                continue
            self.selected.add(index)
        self.generateTags()

    def generateTags(self):
        """
        根据已经选择的索引，生成对应的 tag
        """
        selected = sorted(tuple(self.selected))
        for index in selected:
            if index not in self.selected_tags:
                tag = SelectionTag(self.itemText(index), self)
                tag.deleteClicked.connect(lambda i=index: self.removeSelectIndex(i))
                self.selected_tags[index] = tag
                self.internalLayout.addWidget(tag)

        for index in self.selected_tags.copy():
            if index not in selected:
                self.selected_tags[index].deleteLater()
                self.internalLayout.removeWidget(self.selected_tags[index])
                del self.selected_tags[index]

        self.internalWidget.adjustSize()
        self.internalFrame.setMinimumHeight(self.height() - 7)
        self.internalFrame.setMinimumWidth(self.width() - self.dropButton.width())

    def showEvent(self, a0):
        self.internalFrame.setMinimumHeight(self.height() - 7)
        self.internalFrame.setMinimumWidth(self.width() - self.dropButton.width())

    def removeSelectIndex(self, index: int):
        if index not in self.selected:
            return

        self.selected.remove(index)
        self.generateTags()

    def removeSelectIndexes(self, indexes: list):
        for index in indexes:
            if index in self.selected:
                self.selected.remove(index)
        self.generateTags()

    def clear(self):
        ComboBoxBase.clear(self)

    def _onDropMenuClosed(self):
        self.dropMenu = None
        self.check_boxes = None
        self.all_check_boxes = None

    def _onCheckBoxClicked(self, index: int, checked):
        if checked == Qt.Checked:
            self.addSelectIndex(index)
        else:
            self.removeSelectIndex(index)

    def _onSelectAllBoxClicked(self, checked):
        if self.allSelected():
            self.removeSelectIndexes(self.selectedIndex())
            for one_checkbox in self.check_boxes:
                one_checkbox.setChecked(False)
        else:
            self.addSelectIndexes(list(range(len(self.items))))
            for one_checkbox in self.check_boxes:
                one_checkbox.setChecked(True)

    def setCurrentIndex(self, index: int):
        """什么也不做。覆盖这个方法是为了防止 addItem 调用不合时宜的旧方法。"""
        pass

    def _onSelectCheckBox(self, box):
        box.setChecked(not box.isChecked())

    def _showComboMenu(self):
        if not self.items:
            return

        menu = self._createComboMenu()
        menu.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.check_boxes = []
        self.all_check_boxes = []

        listWidget = ListWidget(menu)
        # 去除悬浮时的阴影
        listWidget.entered.disconnect()

        listWidget.setSelectionMode(ListView.NoSelection)
        listWidget.itemClicked.connect(lambda item: self._onSelectCheckBox(self.all_check_boxes[listWidget.row(item)]))
        listWidget.itemDoubleClicked.connect(lambda item: self._onSelectCheckBox(self.all_check_boxes[listWidget.row(item)]))
        if self.show_all_select_option:
            checkbox = CheckBox(self.tr("全选"), parent=menu)
            checkbox.setChecked(len(self.selected) == len(self.items))
            checkbox.stateChanged.connect(lambda c: self._onSelectAllBoxClicked(c))
            qItem = QListWidgetItem(listWidget)
            qItem.setSizeHint(checkbox.size())
            listWidget.addItem(qItem)
            listWidget.setItemWidget(qItem, checkbox)
            self.all_check_boxes.append(checkbox)

        for i, item in enumerate(self.items):
            checkbox = CheckBox(item.text, parent=menu)
            checkbox.setChecked(i in self.selected)
            checkbox.stateChanged.connect(lambda c, index=i: self._onCheckBoxClicked(index, c))
            self.check_boxes.append(checkbox)
            self.all_check_boxes.append(checkbox)
            qItem = QListWidgetItem(listWidget)
            qItem.setSizeHint(checkbox.size())
            listWidget.addItem(qItem)
            listWidget.setItemWidget(qItem, checkbox)

        listWidget.adjustSize()
        menu.addWidget(listWidget, selectable=False)

        if menu.view.width() < self.width():
            menu.view.setMinimumWidth(self.width())
            menu.adjustSize()
        if menu.view.height() < listWidget.height():
            menu.view.setMinimumHeight(listWidget.height())
            menu.adjustSize()

        menu.setMaxVisibleItems(self.maxVisibleItems())
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.closedSignal.connect(self._onDropMenuClosed)
        self.dropMenu = menu

        # determine the animation type by choosing the maximum height of view
        x = -menu.width()//2 + menu.layout().contentsMargins().left() + self.width()//2
        pd = self.mapToGlobal(QPoint(x, self.height()))
        hd = menu.view.heightForAnimation(pd, MenuAnimationType.DROP_DOWN)

        pu = self.mapToGlobal(QPoint(x, 0))
        hu = menu.view.heightForAnimation(pu, MenuAnimationType.PULL_UP)

        if hd >= hu:
            menu.view.adjustSize(pd, MenuAnimationType.DROP_DOWN)
            menu.exec(pd, aniType=MenuAnimationType.DROP_DOWN)
        else:
            menu.view.adjustSize(pu, MenuAnimationType.PULL_UP)
            menu.exec(pu, aniType=MenuAnimationType.PULL_UP)

    def selectedItems(self):
        return [self.items[index] for index in self.selected]
