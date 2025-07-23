# coding:utf-8
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel
from qfluentwidgets import Dialog, PushButton, ScrollArea, FluentIcon, CheckBox, StrongBodyLabel, BodyLabel

from app.utils import StyleSheet


class CardManagerDialog(Dialog):
    """卡片管理对话框"""
    cardsSelected = pyqtSignal(list)  # 发出选中的卡片ID列表

    def __init__(self, available_cards: dict, parent=None):
        super().__init__("添加功能卡片", "选择要添加到主界面的功能卡片", parent)
        self.available_cards = available_cards
        self.selected_cards = []

        self.setupUI()

    def setupUI(self):
        """设置UI"""
        # 创建滚动区域
        self.scrollArea = ScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollLayout = QVBoxLayout(self.scrollWidget)

        self.scrollArea.setObjectName("NoticeSettingInterface")
        self.scrollWidget.setObjectName("view")

        StyleSheet.NOTICE_SETTING_INTERFACE.apply(self.scrollArea)
        StyleSheet.NOTICE_SETTING_INTERFACE.apply(self.scrollWidget)

        self.checkboxes = {}

        # 为每个可用卡片创建复选框
        for card_id, card_def in self.available_cards.items():
            checkbox_widget = self.createCardCheckbox(card_id, card_def)
            self.scrollLayout.addWidget(checkbox_widget)

        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setFixedSize(400, 300)  # 设置固定高度

        # 添加到对话框布局
        self.textLayout.addWidget(self.scrollArea)

        # 修改按钮文本
        self.yesButton.setText("添加选中卡片")
        self.cancelButton.setText("取消")

        # 连接信号
        self.yesButton.clicked.connect(self.onConfirmed)

    def createCardCheckbox(self, card_id: str, card_def: dict):
        """创建卡片复选框组件"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 5, 10, 5)

        # 复选框
        checkbox = CheckBox()
        checkbox.stateChanged.connect(lambda state: self.onCheckboxChanged(card_id, state))

        widget.mouseReleaseEvent = lambda event: checkbox.setChecked(not checkbox.isChecked())
        self.checkboxes[card_id] = checkbox

        # 卡片信息
        info_layout = QVBoxLayout()
        title_label = StrongBodyLabel(card_def['title'])
        content_label = BodyLabel(card_def['content'])

        info_layout.addWidget(title_label)
        info_layout.addWidget(content_label)

        layout.addWidget(checkbox)
        layout.addLayout(info_layout, 1)

        widget.setFixedHeight(75)

        return widget

    def onCheckboxChanged(self, card_id: str, state: int):
        """复选框状态改变"""
        if state == Qt.Checked:
            if card_id not in self.selected_cards:
                self.selected_cards.append(card_id)
        else:
            if card_id in self.selected_cards:
                self.selected_cards.remove(card_id)

    def onConfirmed(self):
        """确认添加"""
        if self.selected_cards:
            self.cardsSelected.emit(self.selected_cards)
        self.accept()
