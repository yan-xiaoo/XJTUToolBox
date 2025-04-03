from typing import List

from PyQt5.QtCore import pyqtSlot, Qt, pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, BreadcrumbBar

from app.sub_interfaces.NoticeChoiceInterface import NoticeChoiceInterface
from app.utils import StyleSheet
from notification import NotificationManager


class NoticeSettingInterface(ScrollArea):
    """
    此类为通知网站选择与过滤器选择的主界面。
    需要注意的是，此界面只是一个空壳，用于提供左上角的面包屑导航，其实际内容可能为
    NoticeChoiceInterface（选择网站的界面），NoticeRuleInterface（设置过滤规则的界面）等
    """
    # 退出此界面
    quit = pyqtSignal()

    def __init__(self, manager: NotificationManager, notice_interface, parent=None):
        """
        创建一个主界面。
        :param manager: 通知管理器。此类将会读取或修改其中的订阅内容
        :param notice_interface: 父界面，用于面包屑返回跳转
        :param parent: 父组件
        """
        super().__init__(parent)
        self.manager = manager
        self.notice_interface = notice_interface

        self.setObjectName("noticeSettingInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        # 面包屑导航和下方的实际页面
        self.breadcrumbBar = BreadcrumbBar(self)
        self.stackedWidget = QStackedWidget(self)
        self.breadcrumbBar.setSpacing(20)
        self.breadcrumbBar.currentItemChanged.connect(self.switchInterface)

        # 存储所有可能的子页面
        self.children_: List[QWidget] = []

        self.vBoxLayout.setContentsMargins(15, 20, 15, 20)
        self.vBoxLayout.addWidget(self.breadcrumbBar)
        self.vBoxLayout.addWidget(self.stackedWidget, stretch=1, alignment=Qt.AlignHCenter)

        self.choiceInterface = None

        self.init_finished = False
        self.initWidgets()

        StyleSheet.NOTICE_SETTING_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def addInterface(self, widget, text: str):
        """
        添加一个自定义组件，此组件将显示在面包屑的最后一个
        :param widget: 待添加的组件
        :param text: 显示在面包屑导航上的名称
        """
        if not widget.objectName():
            raise ValueError("Widget must have an object name.")

        self.stackedWidget.addWidget(widget)
        self.children_.append(widget)
        self.breadcrumbBar.addItem(widget.objectName(), text)

    def initWidgets(self):
        self.init_finished = False
        for one in self.children_:
            self.stackedWidget.removeWidget(one)

        self.children_ = []
        self.breadcrumbBar.clear()

        self.breadcrumbBar.addItem(self.notice_interface.objectName(), self.tr("通知查询"))
        # 重建一下
        self.choiceInterface = NoticeChoiceInterface(self.manager, self.notice_interface.main_window, self)
        self.choiceInterface.quit.connect(self.onQuit)
        self.addInterface(self.choiceInterface, self.tr("设置查询网站"))
        self.init_finished = True

    def showEvent(self, a0):
        self.initWidgets()

    @pyqtSlot()
    def onQuit(self):
        self.quit.emit()
        self.notice_interface.main_window.switchTo(self.notice_interface)

    @pyqtSlot(str)
    def switchInterface(self, objectName):
        # 特殊处理以下返回上一页的逻辑
        if objectName == self.notice_interface.objectName():
            # 组件库老是犯病，在添加子组件时直接调用 switchInterface
            # 但如果还在初始化阶段，下面的切换页面函数被调用就会完蛋
            # 因此在 initWidgets 里面记录 init_finished 变量，以得知当前是不是正在初始化阶段
            if self.init_finished:
                self.quit.emit()
                self.notice_interface.main_window.switchTo(self.notice_interface)
            return

        for one in self.children_:
            if one.objectName() == objectName:
                self.stackedWidget.setCurrentWidget(one)
                break
        else:
            raise ValueError(f"Object name {objectName} not found.")
