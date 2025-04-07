import json

from PyQt5.QtCore import Qt, pyqtSlot, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QActionGroup
from qfluentwidgets import ScrollArea, CommandBar, FluentIcon, Action, BodyLabel, PrimaryPushButton, \
    TransparentDropDownPushButton, setFont, CheckableMenu, MenuIndicatorType, InfoBarPosition, InfoBar, CaptionLabel

from ..components.NoticeCard import NoticeCard
from ..threads.NoticeThread import NoticeThread
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet
from ..utils.cache import cacheManager, dataManager
from notification import NotificationManager, Notification


class NoticeInterface(ScrollArea):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)

        self.setObjectName("noticeInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.main_window = main_window

        self.commandBar = CommandBar(self)
        self.commandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.editAction = Action(FluentIcon.EDIT, self.tr("编辑查询网站"), self.commandBar)
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
        self.sourceSortGroup = QActionGroup(self)
        self.sourceUpAction = Action(FluentIcon.UP, self.tr("来源正序"), self, checkable=True)
        self.sourceDownAction = Action(FluentIcon.DOWN, self.tr("来源倒序"), self, checkable=True)
        self.sourceNoAction = Action(FluentIcon.HIDE, self.tr("不按来源排序"), self, checkable=True)
        self.sourceSortGroup.addAction(self.sourceUpAction)
        self.sourceSortGroup.addAction(self.sourceDownAction)
        self.sourceSortGroup.addAction(self.sourceNoAction)
        # 时间排序选项
        self.timeSortGroup = QActionGroup(self)
        self.timeUpAction = Action(FluentIcon.UP, self.tr("时间新-旧"), self, checkable=True)
        self.timeDownAction = Action(FluentIcon.DOWN, self.tr("时间旧-新"), self, checkable=True)
        self.timeSortGroup.addAction(self.timeUpAction)
        self.timeSortGroup.addAction(self.timeDownAction)

        # 默认排序方式
        self.sourceNoAction.setChecked(True)
        self.timeUpAction.setChecked(True)

        self.sourceUpAction.triggered.connect(self.sort_by_selected_method)
        self.sourceDownAction.triggered.connect(self.sort_by_selected_method)
        self.sourceNoAction.triggered.connect(self.sort_by_selected_method)
        self.timeUpAction.triggered.connect(self.sort_by_selected_method)
        self.timeDownAction.triggered.connect(self.sort_by_selected_method)

        # 排序菜单
        self.sortMenu = CheckableMenu(parent=self, indicatorType=MenuIndicatorType.RADIO)
        self.sortMenu.addActions([
            self.sourceUpAction,
            self.sourceDownAction,
            self.sourceNoAction,
        ])
        self.sortMenu.addSeparator()
        self.sortMenu.addActions([
            self.timeUpAction,
            self.timeDownAction
        ])

        button.setMenu(self.sortMenu)
        self.commandBar.addWidget(button)

        self.commandBar.setMinimumWidth(450)
        self.vBoxLayout.addWidget(self.commandBar, alignment=Qt.AlignTop | Qt.AlignHCenter)
        self.filterHintLabel = CaptionLabel(self.tr("已启用过滤规则"), self)
        self.vBoxLayout.addWidget(self.filterHintLabel, alignment=Qt.AlignTop | Qt.AlignHCenter)
        self.filterHintLabel.setVisible(False)

        # 通知管理器
        self.noticeManager = self.load_or_create_manager()
        self.noticeThread = NoticeThread(self.noticeManager)
        self.noticeThread.notices.connect(self.onGetNotices)
        self.noticeThread.error.connect(self.onThreadError)
        self.noticeThread.finished.connect(self.unlock)
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

        self.updateFilterHint()

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

        # 控制页面只显示最新的一条通知
        self._onlyNotice = None

        StyleSheet.NOTICE_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def lock(self):
        """
        锁定网络通信相关的元素
        """
        self.editAction.setEnabled(False)
        self.emptyButton.setEnabled(False)
        self.refreshAction.setEnabled(False)

    def unlock(self):
        """
        解锁网络通信相关的元素
        """
        self.editAction.setEnabled(True)
        self.emptyButton.setEnabled(True)
        self.refreshAction.setEnabled(True)

    def updateFilterHint(self):
        """
        根据当前是否真的启用过滤规则，决定是否显示过滤规则提示
        """
        if self.noticeManager.subscription:
            for one in self.noticeManager.subscription:
                if one in self.noticeManager.ruleset:
                    if any([o.enable for o in self.noticeManager.ruleset[one]]):
                        # 如果有规则集启用，则显示提示
                        self.filterHintLabel.setVisible(True)
                        break
            else:
                self.filterHintLabel.setVisible(False)
        else:
            self.filterHintLabel.setVisible(False)

    def error(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个错误的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT,parent=parent, isClosable=True)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    @pyqtSlot()
    def onEditButtonClicked(self):
        self.main_window.switchTo(self.main_window.notice_setting_interface)

    @pyqtSlot()
    def onGetNoticeButtonClicked(self):
        self.processWidget.setVisible(True)
        self.lock()
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

    def sort_notices(self, source_primary=True, reverse_source=False, reverse_time=True):
        """
        对通知进行排序。未读通知永远在最上方
        :param source_primary: 是否先根据通知来源排序，再根据时间排序
        :param reverse_source: 如果按照通知来源排序，是否按照字母顺序倒序显示来源
        :param reverse_time: 是否反向排序。True: 从最新-最旧；False: 从最旧-最新
        """
        self.notices.sort(key=lambda x: x.date, reverse=reverse_time)

        if source_primary:
            self.notices.sort(key=lambda x: x.source.value, reverse=reverse_source)

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
        source_primary = not self.sourceNoAction.isChecked()
        reverse_source = self.sourceUpAction.isChecked()
        reverse_time = self.timeUpAction.isChecked()
        self.sort_notices(source_primary, reverse_source, reverse_time)

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
            # 创建通知卡片对象
            notice_card = NoticeCard(notice, self.noticeFrame)
            notice_card.noticeChanged.connect(self.onNoticeChanged)
            notice_card.noticeClicked.connect(self.onNoticeClicked)
            # 添加到通知显示界面
            self.noticeFrameLayout.addWidget(notice_card)
            # 添加到通知列表
            self.noticeWidgets.append(notice_card)

        self.sort_by_selected_method()

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

    def save_manager(self):
        """
        保存当前通知管理器的信息
        """
        config = self.noticeManager.dump_config()
        dataManager.write_json("notification_config.json", config, allow_overwrite=True)

    @pyqtSlot()
    def onSettingQuit(self):
        """
        在退出通知设置界面时，会被回调的函数。此函数中需要保存 manager 的内容，过滤通知
        """
        self.save_manager()
        # 过滤通知
        index = 0
        while True:
            if index >= len(self.notices):
                break
            one = self.notices[index]
            if not self.noticeManager.satisfy_filter(one):
                self.notices.pop(index)
                one_widget = self.noticeWidgets[index]
                self.noticeFrameLayout.removeWidget(one_widget)
                self.noticeWidgets.remove(one_widget)
                one_widget.deleteLater()
                index -= 1
            index += 1

        self.save_notification()
        self.updateFilterHint()
        if not self.noticeManager.subscription:
            self.switchTo(self.startFrame)
        else:
            # 有通知配置但是没有通知时就切换到提示你获取通知的界面
            if self.notices:
                self.switchTo(self.noticeFrame)
                # 重新获取通知，以获得满足条件的通知
                self.onGetNoticeButtonClicked()
            else:
                self.switchTo(self.emptyFrame)
