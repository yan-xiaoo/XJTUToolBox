from PyQt5.QtCore import pyqtSlot, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout
from qfluentwidgets import PrimaryPushButton, TitleLabel

from ..components.NoticeSourceCard import NoticeSourceCard
from notification import NotificationManager, Source


class NoticeChoiceInterface(QFrame):
    """
    本类为选择通知网站的具体页面
    """
    # 退出此界面
    quit = pyqtSignal()

    def __init__(self, manager: NotificationManager, main_window, parent=None):
        """
        创建一个选择通知网站的页面
        :param manager: 通知管理器
        :param main_window: 主界面的引用，用于切换回通知查询界面
        :param parent: 父组件
        """
        super().__init__(parent)

        self.manager = manager
        self.main_window = main_window
        self.setObjectName("NoticeChoiceInterface")

        self.vBoxLayout = QVBoxLayout(self)

        self.label = TitleLabel(self.tr("选择需要查询的网站"), self)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.label, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addStretch(1)

        for one_source in list(Source):
            card = NoticeSourceCard(one_source, one_source in self.manager.subscription, self)
            card.checkChanged.connect(self.onSourceStateChanged)
            self.vBoxLayout.addWidget(card)

        self.vBoxLayout.addStretch(2)
        self.returnButton = PrimaryPushButton(self.tr("完成"), self)
        self.returnButton.clicked.connect(self.onReturnButtonClicked)
        self.vBoxLayout.addWidget(self.returnButton)

    @pyqtSlot(bool, Source)
    def onSourceStateChanged(self, state: bool, source: Source):
        """
        当用户选择或取消选择某个网站时，发出信号
        :param state: 是否选中
        :param source: 选中的网站
        """
        if state:
            self.manager.add_subscription(source)
        else:
            self.manager.remove_subscription(source)

    @pyqtSlot()
    def onReturnButtonClicked(self):
        """
        当用户点击完成按钮时，返回到通知查询界面
        """
        self.quit.emit()
