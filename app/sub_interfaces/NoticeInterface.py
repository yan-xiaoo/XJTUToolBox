import json

from PyQt5.QtCore import Qt, pyqtSlot, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QActionGroup
from qfluentwidgets import ScrollArea, CommandBar, FluentIcon, Action, BodyLabel, PrimaryPushButton, \
    TransparentDropDownPushButton, setFont, CheckableMenu, MenuIndicatorType

from ..components.NoticeCard import NoticeCard
from ..threads.NoticeThread import NoticeThread
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet, logger
from ..utils.cache import cacheManager, dataManager
from notification import NotificationManager, Notification


class NoticeInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("noticeInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.commandBar = CommandBar(self)
        self.commandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.editAction = Action(FluentIcon.EDIT, self.tr("编辑过滤条件"), self.commandBar)
        self.editAction.triggered.connect(self.onEditButtonClicked)
        self.refreshAction = Action(FluentIcon.SYNC, self.tr("立刻刷新"), self.commandBar)
        self.refreshAction.triggered.connect(self.onGetNoticeButtonClicked)
        self.confirmAction = Action(FluentIcon.ACCEPT, self.tr("全部已读"), self.commandBar)
        self.confirmAction.triggered.connect(self.onReadAllButtonClicked)
        self.commandBar.addAction(self.editAction)
        self.commandBar.addAction(self.refreshAction)
        self.commandBar.addAction(self.confirmAction)
        # 排序菜单的按钮
        button = TransparentDropDownPushButton(FluentIcon.SYNC, self.tr("排序方式"))
        button.setFixedHeight(34)
        setFont(button, 12)
        # 几个排序选项
        self.sortGroup = QActionGroup(self)
        self.sourceTimeReverseAction = Action(FluentIcon.SEARCH, self.tr("来源-时间最新"), self.commandBar, checkable=True)
        self.sourceTimeReverseAction.triggered.connect(lambda: self.sort_notices(source_primary=True, reverse_time=True))
        self.sourceTimeAction = Action(FluentIcon.SEARCH, self.tr("来源-时间最旧"), self.commandBar, checkable=True)
        self.sourceTimeAction.triggered.connect(lambda: self.sort_notices(source_primary=True, reverse_time=False))
        self.timeReverseAction = Action(FluentIcon.UP, self.tr("时间最新"), self.commandBar, checkable=True)
        self.timeReverseAction.triggered.connect(lambda: self.sort_notices(source_primary=False, reverse_time=True))
        self.timeAction = Action(FluentIcon.DOWN, self.tr("时间最旧"), self.commandBar, checkable=True)
        self.timeAction.triggered.connect(lambda: self.sort_notices(source_primary=False, reverse_time=False))

        self.sortGroup.addAction(self.sourceTimeReverseAction)
        self.sortGroup.addAction(self.sourceTimeAction)
        self.sortGroup.addAction(self.timeReverseAction)
        self.sortGroup.addAction(self.timeAction)
        # 默认排序方式
        self.timeReverseAction.setChecked(True)

        # 排序菜单
        self.sortMenu = CheckableMenu(parent=self, indicatorType=MenuIndicatorType.RADIO)
        self.sortMenu.addActions([
            self.sourceTimeReverseAction,
            self.sourceTimeAction,
            self.timeReverseAction,
            self.timeAction
        ])
        button.setMenu(self.sortMenu)
        self.commandBar.addWidget(button)

        self.commandBar.setMinimumWidth(450)
        self.vBoxLayout.addWidget(self.commandBar, alignment=Qt.AlignTop | Qt.AlignHCenter)

        # 通知管理器
        self.noticeManager = self.load_or_create_manager()
        self.noticeThread = NoticeThread(self.noticeManager)
        self.noticeThread.notices.connect(self.onGetNotices)
        self.processWidget = ProcessWidget(self.noticeThread, self, stoppable=True)
        self.vBoxLayout.addWidget(self.processWidget, alignment=Qt.AlignTop | Qt.AlignHCenter)
        self.processWidget.setVisible(False)

        # 没有配置时的界面
        self.startFrame = QFrame(self.view)
        self.startFrameLayout = QVBoxLayout(self.startFrame)

        self.startLabel = BodyLabel(self.tr("你需要查询哪些网站的通知？"), self.startFrame)
        self.startButton = PrimaryPushButton(self.tr("添加通知配置"), self.startFrame)
        self.startFrameLayout.addWidget(self.startLabel, alignment=Qt.AlignHCenter)
        self.startButton.setFixedWidth(150)
        self.startButton.clicked.connect(self.onEditButtonClicked)
        self.startFrameLayout.addWidget(self.startButton, alignment=Qt.AlignHCenter)

        self.vBoxLayout.addWidget(self.startFrame, stretch=1, alignment=Qt.AlignVCenter | Qt.AlignHCenter)

        # 该显示通知但是一点通知都没有时候的界面
        self.emptyFrame = QFrame(self.view)
        self.emptyFrameLayout = QVBoxLayout(self.emptyFrame)
        self.emptyLabel = BodyLabel(self.tr("尚无已获取的通知"), self.emptyFrame)
        self.emptyFrameLayout.addWidget(self.emptyLabel, alignment=Qt.AlignHCenter)
        self.emptyButton = PrimaryPushButton(self.tr("点击获取通知"), self.emptyFrame)
        self.emptyButton.setFixedWidth(150)
        self.emptyButton.clicked.connect(self.onGetNoticeButtonClicked)
        self.emptyFrameLayout.addWidget(self.emptyButton, alignment=Qt.AlignHCenter)

        self.vBoxLayout.addWidget(self.emptyFrame, stretch=1, alignment=Qt.AlignVCenter | Qt.AlignHCenter)

        # 通知显示界面
        self.noticeFrame = QFrame(self.view)
        self.noticeFrameLayout = QVBoxLayout(self.noticeFrame)
        # 通知卡片对象
        self.noticeWidgets = []

        self.vBoxLayout.addWidget(self.noticeFrame, stretch=1, alignment=Qt.AlignHCenter)

        # 已有的通知
        try:
            notice_data = cacheManager.read_json("notification.json")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            notice_data = []
        self.notices = self.noticeManager.load_notifications(notice_data)
        self.sort_by_selected_method()
        for notice in self.notices:
            # 创建通知卡片对象
            notice_card = NoticeCard(notice, self.noticeFrame)
            notice_card.noticeChanged.connect(self.onNoticeChanged)
            notice_card.noticeClicked.connect(self.onNoticeClicked)
            # 添加到通知显示界面
            self.noticeFrameLayout.addWidget(notice_card)
            # 添加到通知列表
            self.noticeWidgets.append(notice_card)

        # 没有通知配置时就切换到提示你添加配置的界面
        if not self.noticeManager.subscription:
            self.switchTo(self.startFrame)
        else:
            # 有通知配置但是没有通知时就切换到提示你获取通知的界面
            if self.notices:
                self.switchTo(self.noticeFrame)
            else:
                self.switchTo(self.emptyFrame)

        StyleSheet.NOTICE_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

    @pyqtSlot()
    def onEditButtonClicked(self):
        pass

    @pyqtSlot()
    def onGetNoticeButtonClicked(self):
        self.processWidget.setVisible(True)
        # 首次获取通知时，获取两页；其他情况下，获取一页
        if not self.notices:
            self.noticeThread.pages = 2
        else:
            self.noticeThread.pages = 1
        self.noticeThread.start()

    @pyqtSlot()
    def onReadAllButtonClicked(self):
        """
        全部已读按钮被点击
        """
        for notice in self.notices:
            notice.is_read = True
        for one in self.noticeWidgets:
            one.updateChangeReadStatusAction()
        # 更新通知列表
        self.save_notification()

    def sort_notices(self, source_primary=True, reverse_time=True):
        """
        对通知进行排序。未读通知永远在最上方
        :param source_primary: 是否先根据通知来源排序，再根据时间排序
        :param reverse_time: 是否反向排序。True: 从最新-最旧；False: 从最旧-最新
        """
        if reverse_time:
            self.notices.sort(key=lambda x: x.date, reverse=True)
        else:
            self.notices.sort(key=lambda x: x.date)


        if source_primary:
            self.notices.sort(key=lambda x: x.source.value, reverse=True)

        self.notices.sort(key=lambda x: x.is_read, reverse=False)

        # 更新通知列表
        for one in self.noticeWidgets:
            self.noticeFrameLayout.removeWidget(one)
        if self.noticeWidgets:
            self.noticeWidgets.sort(key=lambda x: self.notices.index(x.notice))
        for one in self.noticeWidgets:
            self.noticeFrameLayout.addWidget(one)
        self.save_notification()

    def sort_by_selected_method(self):
        """
        根据选中的排序方式对通知进行排序
        """
        if self.sourceTimeReverseAction.isChecked():
            self.sort_notices(source_primary=True, reverse_time=True)
        elif self.sourceTimeAction.isChecked():
            self.sort_notices(source_primary=True, reverse_time=False)
        elif self.timeReverseAction.isChecked():
            self.sort_notices(source_primary=False, reverse_time=True)
        elif self.timeAction.isChecked():
            self.sort_notices(source_primary=False, reverse_time=False)

    @pyqtSlot(Notification)
    def onNoticeChanged(self, notice):
        """
        当通知的已读状态发生变化时，保存通知配置
        """
        # 更新通知列表
        self.save_notification()

    @pyqtSlot(Notification)
    def onNoticeClicked(self, notice):
        """
        显示通知详情
        """
        try:
            index = self.notices.index(notice)
        except ValueError:
            logger.warning("通知不存在")
        else:
            # 显示通知详情
            notice.is_read = True
            for one in self.noticeWidgets:
                one.updateChangeReadStatusAction()
            # 更新通知列表
            self.save_notification()
            QDesktopServices().openUrl(QUrl(notice.link))

    @pyqtSlot(list)
    def onGetNotices(self, notices):
        for notice in notices:
            # 忽略重复的通知
            if notice in self.notices:
                continue
            self.notices.append(notice)
        self.sort_by_selected_method()
        for notice in self.notices:
            # 创建通知卡片对象
            notice_card = NoticeCard(notice, self.noticeFrame)
            notice_card.noticeChanged.connect(self.onNoticeChanged)
            notice_card.noticeClicked.connect(self.onNoticeClicked)
            # 添加到通知显示界面
            self.noticeFrameLayout.addWidget(notice_card)
            # 添加到通知列表
            self.noticeWidgets.append(notice_card)
        # 如果存在通知，切换到通知显示界面
        if self.notices:
            self.switchTo(self.noticeFrame)
        # 更新通知列表
        self.save_notification()

    def save_notification(self):
        """
        保存通知配置
        """
        list_ = self.noticeManager.dump_notifications(self.notices)
        cacheManager.write_json("notification.json", list_, allow_overwrite=True)

    def switchTo(self, item):
        """
        在自身的初始界面和通知显示界面之间切换
        """
        if item == self.startFrame:
            self.startFrame.setVisible(True)
            self.emptyFrame.setVisible(False)
            self.noticeFrame.setVisible(False)
        elif item == self.emptyFrame:
            self.startFrame.setVisible(False)
            self.emptyFrame.setVisible(True)
            self.noticeFrame.setVisible(False)
        else:
            self.startFrame.setVisible(False)
            self.emptyFrame.setVisible(False)
            self.noticeFrame.setVisible(True)

    @staticmethod
    def load_or_create_manager():
        """
        从缓存中加载通知管理器，如果不存在则创建一个新的通知管理器
        """
        try:
            config_file = dataManager.read_json("notification_config.json")
            manager = NotificationManager.load_or_create(config_file)
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            manager = NotificationManager()
        return manager

