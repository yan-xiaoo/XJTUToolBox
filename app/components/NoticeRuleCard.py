from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QGraphicsOpacityEffect
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, PushButton, TransparentToolButton, PrimaryPushButton, \
    FlyoutViewBase, Flyout
from qfluentwidgets import FluentIcon as FIF

from notification import Ruleset


class DeleteFlyoutView(FlyoutViewBase):
    # 确认删除的信号
    confirmed = pyqtSignal()
    # 取消删除什么都不用做，所以不需要信号
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.label = BodyLabel(self.tr("确定删除此规则吗？"), self)
        self.confirmButton = PrimaryPushButton(self.tr("删除"), self)
        self.cancelButton = PushButton(self.tr("取消"), self)

        self.vBoxLayout.setSpacing(12)
        self.vBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.vBoxLayout.addWidget(self.label)

        self.hBoxLayout = QHBoxLayout()
        self.hBoxLayout.setSpacing(12)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.confirmButton)
        self.hBoxLayout.addWidget(self.cancelButton)
        self.vBoxLayout.addLayout(self.hBoxLayout)

        self.confirmButton.clicked.connect(self.onConfirmed)
        self.cancelButton.clicked.connect(lambda: self.parent().close())

    @pyqtSlot()
    def onConfirmed(self):
        self.confirmed.emit()


class AddRuleCard(CardWidget):
    """
    显示添加规则的卡片，点击后弹出添加规则的对话框
    """
    # 被点击的信号
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.titleLabel = BodyLabel(self.tr("添加规则"), self)
        self.contentLabel = CaptionLabel(self.tr("点击此卡片，添加新的通知过滤规则"), self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 20, 11)
        self.hBoxLayout.setSpacing(15)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout, stretch=1)

    def mousePressEvent(self, e):
        """
        鼠标点击事件，发出clicked信号
        :param e: 事件
        """
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class NoticeRuleCard(CardWidget):
    """
    显示通知过滤规则的卡片，可以选择编辑/删除/禁用/启用规则
    """
    # 编辑本卡片对应规则的信号
    editRuleSet = pyqtSignal(Ruleset)
    # 删除本卡片对应规则的信号
    deleteRuleSet = pyqtSignal(Ruleset)

    def __init__(self, ruleset: Ruleset, parent=None):
        super().__init__(parent)

        self.ruleset = ruleset

        self.titleLabel = BodyLabel(ruleset.name if ruleset.name is not None else "", self)
        self.contentLabel = CaptionLabel(ruleset.stringify(), self)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 20, 11)
        self.hBoxLayout.setSpacing(15)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout, stretch=1)

        self.editButton = PrimaryPushButton(self.tr("编辑"), self)
        self.editButton.clicked.connect(self.onEditButtonClicked)
        self.enableButton = PushButton(self.tr("禁用") if self.ruleset.enable else self.tr("启用"), self)
        self.enableButton.clicked.connect(self.onEnableButtonClicked)
        self.deleteButton = TransparentToolButton(FIF.DELETE, self)
        self.deleteButton.clicked.connect(self.onDeleteButtonClicked)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)  # 默认不透明
        if not self.ruleset.enable:
            self.opacity_effect.setOpacity(0.5)

        self.hBoxLayout.addWidget(self.editButton, 0, Qt.AlignRight)
        self.hBoxLayout.addWidget(self.enableButton, 0, Qt.AlignRight)
        self.hBoxLayout.addWidget(self.deleteButton, 0, Qt.AlignRight)

    def updateDisplay(self):
        """
        ruleset 对象可能会被修改，所以需要更新显示
        """
        self.titleLabel.setText(self.ruleset.name if self.ruleset.name is not None else "")
        self.contentLabel.setText(self.ruleset.stringify())
        self.enableButton.setText(self.tr("禁用") if self.ruleset.enable else self.tr("启用"))
        self.opacity_effect.setOpacity(1.0 if self.ruleset.enable else 0.5)

    @pyqtSlot()
    def onEnableButtonClicked(self):
        self.ruleset.enable = not self.ruleset.enable
        self.enableButton.setText(self.tr("禁用") if self.ruleset.enable else self.tr("启用"))
        self.opacity_effect.setOpacity(1.0 if self.ruleset.enable else 0.5)

    @pyqtSlot()
    def onEditButtonClicked(self):
        # 发出编辑信号
        self.editRuleSet.emit(self.ruleset)

    @pyqtSlot()
    def onDeleteButtonClicked(self):
        view = DeleteFlyoutView(self)
        view.confirmed.connect(self.onDeleteConfirmed)
        Flyout.make(view=view, target=self.deleteButton, parent=self)

    @pyqtSlot()
    def onDeleteConfirmed(self):
        self.deleteRuleSet.emit(self.ruleset)
