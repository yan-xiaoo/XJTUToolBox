from typing import List

from PyQt5.QtCore import pyqtSlot, Qt, pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, BreadcrumbBar

from app.sub_interfaces.NoticeChoiceInterface import NoticeChoiceInterface
from app.sub_interfaces.NoticeRuleInterface import NoticeRuleInterface
from app.sub_interfaces.RuleSetInterface import RuleSetInterface
from app.utils import StyleSheet
from notification import NotificationManager, Source, Ruleset


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
        self.ruleInterface = None
        self.ruleSetInterface = None

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
        self.choiceInterface.setRuleClicked.connect(self.onModifyRuleClicked)
        self.ruleInterface = None
        self.ruleSetInterface = None
        self.addInterface(self.choiceInterface, self.tr("设置查询网站"))
        self.init_finished = True

    def showEvent(self, a0):
        self.initWidgets()

    @pyqtSlot()
    def onCompleted(self):
        """
        移动到上一个页面，用于除了 NoticeChoiceInterface 外，其他界面“完成”键的槽函数
        """
        if len(self.breadcrumbBar.items) > 1:
            self.breadcrumbBar.setCurrentIndex(len(self.breadcrumbBar.items) - 2)
            self.children_.pop()
            if len(self.children_) > 0:
                self.switchInterface(self.children_[-1].objectName())

    @pyqtSlot(Source)
    def onModifyRuleClicked(self, source):
        """
        卡片的“设置过滤规则”按钮被点击时的槽函数
        :param source: 需要设置规则的通知来源
        """
        if self.ruleInterface is not None:
            try:
                self.stackedWidget.removeWidget(self.ruleInterface)
                self.children_.remove(self.ruleInterface)
            except ValueError:
                pass

        self.ruleInterface = NoticeRuleInterface(self.manager, source, self)
        self.ruleInterface.editRuleSet.connect(self.onRuleSetClicked)
        self.ruleInterface.quit.connect(self.onCompleted)
        self.addInterface(self.ruleInterface, self.tr("设置过滤规则"))
        self.switchInterface(self.ruleInterface.objectName())

    @pyqtSlot(Ruleset, Source)
    def onRuleSetClicked(self, ruleset, source):
        """
        当“设置过滤规则”的“编辑规则”按钮被点击时的槽函数
        :param ruleset: 需要编辑的规则集。内容为空时，表示添加新的规则集。之所以不允许传入 None，是因为 PyQt 对槽函数数据类型有检查
        :param source: 通知来源
        """
        if self.ruleSetInterface is not None:
            try:
                self.stackedWidget.removeWidget(self.ruleSetInterface)
                self.children_.remove(self.ruleSetInterface)
            except ValueError:
                pass

        if not ruleset.filters:
            ruleset = None
        if source in self.manager.ruleset:
            all_ruleset = self.manager.ruleset[source]
        else:
            all_ruleset = None
        self.ruleSetInterface = RuleSetInterface(ruleset, all_ruleset, self)
        self.ruleSetInterface.quit.connect(self.onCompleted)
        if self.ruleInterface is not None:
            self.ruleSetInterface.finishEdit.connect(self.ruleInterface.onEditFinish)
        self.addInterface(self.ruleSetInterface, self.tr("编辑规则"))
        self.switchInterface(self.ruleSetInterface.objectName())

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
