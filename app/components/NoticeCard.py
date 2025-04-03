from PyQt5.QtCore import Qt, pyqtSlot, QPoint, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, TransparentToolButton, FluentIcon, RoundMenu, Action

from notification import Notification


class NoticeCard(CardWidget):
    """
    显示通知的卡片
    """
    # 当自身托管的通知属性变化时，发出信号
    noticeChanged = pyqtSignal(Notification)
    noticeClicked = pyqtSignal(Notification)

    def __init__(self, notice: Notification, parent=None):
        super().__init__(parent)

        # 用于修改线程信息
        self.notice = notice

        self.titleLabel = BodyLabel(notice.title, self)
        self.contentLabel = CaptionLabel(notice.source.value + "    " + notice.date.isoformat(), self)

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
        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.hBoxLayout.addSpacing(10)

        self.moreButton = TransparentToolButton(FluentIcon.MORE, self)
        self.hBoxLayout.addWidget(self.moreButton, 0, Qt.AlignRight)

        self.changeReadStatusAction = Action(FluentIcon.CHECKBOX, "", self)
        self.changeReadStatusAction.triggered.connect(self.onChangeReadStatusAction)
        self.updateChangeReadStatusAction()

        self.menu = RoundMenu(parent=self)
        self.menu.addAction(self.changeReadStatusAction)

        self.moreButton.setFixedSize(32, 32)
        self.moreButton.clicked.connect(self.onMoreButtonClicked)

    def mousePressEvent(self, event):
        """
        鼠标点击事件
        """
        if event.button() == Qt.LeftButton:
            self.noticeClicked.emit(self.notice)
        super().mousePressEvent(event)

    def onChangeReadStatusAction(self):
        """
        切换已读状态
        """
        self.notice.is_read = not self.notice.is_read
        self.noticeChanged.emit(self.notice)
        self.updateChangeReadStatusAction()

    def updateChangeReadStatusAction(self):
        """
        更新已读状态
        """
        if self.notice.is_read:
            self.changeReadStatusAction.setText("标为未读")
            self.changeReadStatusAction.setIcon(FluentIcon.FLAG)
            self.titleLabel.setTextColor()
        else:
            self.changeReadStatusAction.setText("标为已读")
            self.changeReadStatusAction.setIcon(FluentIcon.ACCEPT)
            self.titleLabel.setTextColor(QColor(70, 73, 156), QColor(142, 141, 200))

    @pyqtSlot()
    def onMoreButtonClicked(self):
        """
        显示更多操作菜单
        """
        x = (self.moreButton.width() - self.menu.width()) // 2 + 10
        pos = self.moreButton.mapToGlobal(QPoint(x, self.moreButton.height()))
        self.menu.exec(pos)
