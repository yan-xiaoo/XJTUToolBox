import datetime
import json
import platform
import sys

from PyQt5.QtCore import Qt, pyqtSlot, QUrl, QTimer
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QActionGroup
from qfluentwidgets import ScrollArea, CommandBar, FluentIcon, Action, BodyLabel, PrimaryPushButton, \
    TransparentDropDownPushButton, setFont, CheckableMenu, MenuIndicatorType, InfoBarPosition, InfoBar, CaptionLabel, \
    MessageBox
from plyer import notification

from ..components.NoticeCard import NoticeCard
from ..threads.NoticeThread import NoticeThread
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet, cfg
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

        self._lastNotices = None
        self._forcePush = False

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
        # 延迟加载通知卡片的相关变量
        self._pendingNotices = self.notices[:]  # 待处理的通知列表
        self._loadIndex = 0  # 当前加载索引
        self._batchSize = 5  # 每批加载的通知数量
        self._loadTimer = QTimer(self)  # 延迟加载定时器
        self._loadTimer.timeout.connect(self._loadNextBatch)

        # 先排序通知数据，但不创建UI组件
        self.sort_notices_data_only()

        # 没有通知配置时就切换到提示你添加配置的界面
        if not self.noticeManager.subscription:
            self.switchTo(self.startFrame)
        else:
            # 有通知配置但是没有通知时就切换到提示你获取通知的界面
            if self.notices:
                self.switchTo(self.noticeFrame)
                # 启动延迟加载
                QTimer.singleShot(100, self._startLoadingNotices)  # 100ms后开始加载
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

    def sort_notices_data_only(self):
        """
        仅对通知数据进行排序，不更新UI
        """
        self.notices.sort(key=lambda x: x.date, reverse=True)
        self.notices.sort(key=lambda x: x.source.value, reverse=False)
        self.notices.sort(key=lambda x: x.is_read, reverse=False)

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

    @pyqtSlot()
    def onTimerSearch(self):
        """
        主界面定时搜索通知计时器超时时的函数
        """
        last_time = cfg.lastSearchTime.value
        now = datetime.datetime.now()
        scheduled_time = datetime.datetime.combine(now.date(), cfg.noticeSearchTime.value)
        if now >= scheduled_time > last_time:
            # 如果当前时间大于定时搜索时间，并且上次搜索时间小于当前时间
            self.startBackgroundSearch()
            # 更新上次搜索时间
            cfg.lastSearchTime.value = now

    def startBackgroundSearch(self, force_push=False):
        """
        启动定时获取通知的线程，开始后台搜索并推送通知
        :param force_push: 是否一定在查询后推送通知，即使没有新通知
        """
        self._forcePush = force_push
        self.noticeThread.pages = 1
        self.noticeThread.notices.connect(self.onGetScheduledNotices)
        self._lastNotices = self.notices[:]
        # 检查一下 manager 里面有没有订阅
        if not self.noticeManager.subscription:
            if self.main_window.isVisible():
                # 没有订阅就不获取通知
                box = MessageBox(self.tr("无法获取通知"), self.tr("您还没有设置要获取通知的网站，请前往通知查询页面设置。"), self.main_window)
                box.yesButton.hide()
                box.cancelButton.setText(self.tr("好的"))
                box.exec()
            return
        self.noticeThread.start()

    @pyqtSlot(list)
    def onGetScheduledNotices(self, notices):
        """
        定时获取通知时，获取到通知的处理函数
        """
        try:
            self.noticeThread.notices.disconnect(self.onGetScheduledNotices)
        except TypeError:
            # 鬼知道为什么会取消连接失败
            pass

        filtered_notices = [notice for notice in notices if notice not in self._lastNotices]
        sources = set()
        count = len(filtered_notices)
        for notice in filtered_notices:
            sources.add(notice.source.value)
        try:
            if count > 0:
                notification.notify(title=self.tr("西安交通大学网站有新的通知"), message=f"{self.tr('来自')} {', '.join(sources)} {self.tr('的')} {count} {self.tr('条新通知')}")
            elif self._forcePush:
                # 如果没有新通知，但是还是要推送通知
                notification.notify(title="没有新的通知", message="现在的通知已经是最新的")
        except NotImplementedError as e:
            if platform.system() == "Darwin":
                if getattr(sys, "frozen", False):
                    # 打包版本不该有问题
                    if self.main_window.isVisible():
                        box = MessageBox(self.tr("推送通知失败"), self.tr("错误信息如下：") + "\n" + str(e), self.main_window)
                        box.yesButton.hide()
                        box.cancelButton.setText(self.tr("好的"))
                        box.exec()
                    else:
                        self.error(self.tr("推送通知失败"), self.tr("错误信息如下：") + "\n" + str(e))
                else:
                    # macOS 源码运行时需要自己装库
                    if self.main_window.isVisible():
                        box = MessageBox(self.tr("推送通知失败"), self.tr("请跟随 GitHub 仓库中 README.md 的指引，安装 pyobjus 库"), self.main_window)
                        box.yesButton.hide()
                        box.cancelButton.setText(self.tr("好的"))
                        box.exec()
                    else:
                        self.error(self.tr("推送通知失败"), self.tr("请跟随 GitHub 仓库中 README.md 的指引，安装 pyobjus 库"))
            else:
                # 其他系统
                if self.main_window.isVisible():
                    box = MessageBox(self.tr("推送通知失败"), self.tr("错误信息如下：") + "\n" + str(e), self.main_window)
                    box.yesButton.hide()
                    box.cancelButton.setText(self.tr("好的"))
                    box.exec()
                else:
                    self.error(self.tr("无法推送通知"), str(e))

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

    @pyqtSlot()
    def _loadNextBatch(self):
        """
        加载下一批通知卡片
        """
        if self._loadIndex >= len(self._pendingNotices):
            # 如果没有更多的通知，停止定时器
            self._loadTimer.stop()
            return

        # 计算当前批次的通知
        endIndex = min(self._loadIndex + self._batchSize, len(self._pendingNotices))
        currentBatch = self._pendingNotices[self._loadIndex:endIndex]

        for notice in currentBatch:
            # 创建通知卡片对象
            notice_card = NoticeCard(notice, self.noticeFrame)
            notice_card.noticeChanged.connect(self.onNoticeChanged)
            notice_card.noticeClicked.connect(self.onNoticeClicked)
            # 添加到通知显示界面
            self.noticeFrameLayout.addWidget(notice_card)
            # 添加到通知列表
            self.noticeWidgets.append(notice_card)

        self._loadIndex = endIndex

    @pyqtSlot()
    def _startLoadingNotices(self):
        """
        开始延迟加载通知卡片
        """
        self._loadTimer.start(100)  # 每100ms加载一批通知

