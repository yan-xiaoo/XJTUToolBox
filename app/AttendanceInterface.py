import typing
from functools import total_ordering

from PyQt5.QtWidgets import QWidget, QStackedWidget, QTableWidgetItem, QFrame, QHeaderView, QAbstractItemView
from PyQt5.QtCore import Qt, pyqtSlot
from qfluentwidgets import ScrollArea, VBoxLayout, Pivot, BodyLabel, PrimaryPushButton, TableWidget, \
    CommandBar, Action, FluentIcon, InfoBar, InfoBarPosition, PipsPager, PipsScrollButtonDisplayMode, MessageBox
from .utils import StyleSheet, accounts, AccountCacheManager, Color
from attendance.attendance import AttendanceFlow, FlowRecordType
from .threads.ProcessWidget import ProcessWidget
from .threads.AttendanceFlowThread import AttendanceFlowThread, AttendanceFlowChoice


class AttendanceFlowWidget(QFrame):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._parent = parent

        self.main_window = main_window
        self.vBoxLayout = VBoxLayout(self)
        self.nothingFrame = self.constructNoAccountFrame()
        self.normalFrame = self.constructWithAccountFrame()

        self.vBoxLayout.addWidget(self.nothingFrame)
        self.vBoxLayout.addWidget(self.normalFrame)

        # 在用户选择查看另一页从而发起网络请求期间，last_page 保持修改前的页数，current_page 保持修改后的页数
        self.last_page = 1
        # self.current_page, self.thread_.page, self.pager.currentIndex 三者应该永远保持一致
        self.current_page = 1

        # 控制页面只显示最新的一条通知
        self._onlyNotice = None

        if len(accounts) > 0:
            self.loadContentCache()
        # 立刻根据当前账户状态更改显示
        self.accountAdded()

        self.thread_.error.connect(self.onThreadError)
        self.thread_.successMessage.connect(self.onThreadSuccess)
        self.thread_.finished.connect(self.unlock)
        self.thread_.flowRecord.connect(self.onGetFlowRecord)
        accounts.accountAdded.connect(self.accountAdded)
        accounts.accountDeleted.connect(self.accountAdded)
        accounts.currentAccountChanged.connect(self.currentAccountChanged)

    @pyqtSlot()
    def accountAdded(self):
        if len(accounts) == 0:
            self.normalFrame.setVisible(False)
            self.nothingFrame.setVisible(True)
        else:
            self.nothingFrame.setVisible(False)
            self.normalFrame.setVisible(True)

    def clearTableContent(self):
        for i in range(self.tableWidget.rowCount()):
            self.tableWidget.setItem(i, 0, QTableWidgetItem(""))
            self.tableWidget.setItem(i, 1, QTableWidgetItem(""))
            self.tableWidget.setItem(i, 2, QTableWidgetItem(""))

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个成功的通知。如果已经存在通知，已存在的通知会被立刻关闭。
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
        self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)

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
        self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)

    @pyqtSlot()
    def currentAccountChanged(self):
        self.clearTableContent()
        self.thread_.account = accounts.current
        # 由于不知道其他用户考勤总共有多少页，因此隐藏分页控件
        self.pager.setVisible(False)
        self.loadContentCache()

    @pyqtSlot()
    def lock(self):
        """锁定一切网络连接有关的元素"""
        self.pager.setEnabled(False)
        self.webVPNLoginAction.setEnabled(False)
        self.normalLoginAction.setEnabled(False)
        self.refreshAction.setEnabled(False)
        self.nextAction.setEnabled(False)
        self.prevAction.setEnabled(False)

    @pyqtSlot()
    def unlock(self):
        """解锁一切网络连接有关的元素"""
        self.pager.setEnabled(True)
        self.webVPNLoginAction.setEnabled(True)
        self.normalLoginAction.setEnabled(True)
        self.refreshAction.setEnabled(True)
        self.nextAction.setEnabled(True)
        self.prevAction.setEnabled(True)

    def askForRelogin(self) -> bool:
        """
        如果用户已经登录，则弹出对话框并询问用户是否要重新登录。如果用户没有登录，此函数直接返回 False。
        :return: 用户选择是否要重新登录
        """
        if self.thread_.session.has_login:
            if self.thread_.last_login_choice == AttendanceFlowChoice.WEBVPN_LOGIN:
                w = MessageBox(self.tr("确认重新登录"),
                               self.tr("你已经通过 WebVPN 登录考勤系统，是否要清除登录信息并重新登录？"),
                               self.parent().parent())
            else:
                w = MessageBox(self.tr("确认重新登录"),
                               self.tr("你已经直接登录考勤系统，是否要清除登录信息并重新登录？"), self.parent().parent())
            w.yesButton.setText(self.tr("确定"))
            w.cancelButton.setText(self.tr("取消"))
            if w.exec():
                return True
        else:
            return False

    def keyReleaseEvent(self, a0):
        if a0.key() == Qt.Key_Space:
            if self.refreshAction.isEnabled():
                self.refreshAction.trigger()
        if a0.key() == Qt.Key_Down or a0.key() == Qt.Key_Right:
            if self.nextAction.isEnabled():
                self.nextAction.trigger()
        if a0.key() == Qt.Key_Up or a0.key() == Qt.Key_Left:
            if self.prevAction.isEnabled():
                self.prevAction.trigger()

    @pyqtSlot()
    def onWebVPNLoginClicked(self):
        if self.askForRelogin():
            self.thread_.session.has_login = False
            self.thread_.session.cookies.clear_session_cookies()
            self.processWidget.setVisible(True)
            self.thread_.choice = AttendanceFlowChoice.WEBVPN_LOGIN
            self.lock()
            self.thread_.start()
            return

        if not self.thread_.session.has_login:
            self.processWidget.setVisible(True)
            self.thread_.choice = AttendanceFlowChoice.WEBVPN_LOGIN
            self.lock()
            self.thread_.start()
            return

    @pyqtSlot()
    def onNormalLoginClicked(self):
        if self.askForRelogin():
            self.thread_.session.has_login = False
            self.thread_.session.cookies.clear_session_cookies()
            self.processWidget.setVisible(True)
            self.thread_.choice = AttendanceFlowChoice.NORMAL_LOGIN
            self.lock()
            self.thread_.start()
            return

        if not self.thread_.session.has_login:
            self.processWidget.setVisible(True)
            self.thread_.choice = AttendanceFlowChoice.NORMAL_LOGIN
            self.lock()
            self.thread_.start()
            return

    @pyqtSlot()
    def onSearchClicked(self):
        self.processWidget.setVisible(True)
        self.thread_.choice = AttendanceFlowChoice.SEARCH
        self.lock()
        self.thread_.start()

    @pyqtSlot()
    def onNextClicked(self):
        if self.current_page >= self.pager.getPageNumber():
            self.success("", self.tr("已经到底啦"), duration=2000, position=InfoBarPosition.TOP_RIGHT,
                         parent=self._parent)
            return
        self.last_page = self.current_page
        self.current_page += 1
        self.thread_.page += 1
        self.onSearchClicked()

    @pyqtSlot()
    def onPrevClicked(self):
        if self.current_page > 1:
            self.last_page = self.current_page
            self.current_page -= 1
            self.thread_.page -= 1
            self.onSearchClicked()
        else:
            self.success("", self.tr("已经到顶啦"), duration=2000, position=InfoBarPosition.TOP_RIGHT,
                            parent=self._parent)

    @pyqtSlot(int)
    def onPageClicked(self, current_index: int):
        if self.current_page - 1 != current_index:
            self.last_page = self.current_page
            self.current_page = current_index + 1
            self.thread_.page = current_index + 1
            self.onSearchClicked()

    @pyqtSlot(dict)
    def onGetFlowRecord(self, record: dict):
        # 在获得了考勤记录后，我们就知道总共有多少页了，因此可以显示分页控件
        self.pager.setVisible(True)
        total_pages = record['total_pages']
        # 设置分页器的可见页数，最多十页
        self.pager.setVisibleNumber(min(total_pages, 10))
        # 如果分页器当前页数不等于总页数，则设置分页器页数
        if self.pager.getPageNumber() != total_pages:
            self.pager.setPageNumber(total_pages)
        self.pager.setCurrentIndex(record['current_page'] - 1)

        self.setTableContent(record['data'])
        self.saveContentCache(record['data'])

    def loadContentCache(self):
        try:
            cache = AccountCacheManager(accounts.current)
            record_list = cache.read_json("attendance_flow.json")
            record = [AttendanceFlow.from_json(one) for one in record_list]
            self.setTableContent(record)
        except Exception:
            pass

    def saveContentCache(self, record: list):
        cache = AccountCacheManager(accounts.current)
        record_list = [one.json() for one in record]
        cache.write_json("attendance_flow.json", record_list, allow_overwrite=True)

    @pyqtSlot(str)
    def onThreadSuccess(self, msg):
        self.success(self.tr("成功"), msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=self._parent)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self._parent)

        self.current_page = self.last_page
        self.thread_.page = self.last_page
        self.pager.setCurrentIndex(self.current_page - 1)

    @pyqtSlot()
    def onThreadTerminated(self):
        """
        线程被主动终止后执行的操作
        """
        # 复原更改过的页数信息
        self.current_page = self.last_page
        self.thread_.page = self.last_page
        self.pager.setCurrentIndex(self.current_page - 1)

    def constructNoAccountFrame(self) -> QFrame:
        frame = QFrame(self)
        vBoxLayout = VBoxLayout(frame)
        self.label = BodyLabel(self.tr("你尚未登录任何账户"), self)
        vBoxLayout.addWidget(self.label, alignment=Qt.AlignHCenter)
        self.button = PrimaryPushButton(self.tr("前往登录"), self)
        self.button.clicked.connect(lambda: self.main_window.switchTo(self.main_window.account_interface))
        vBoxLayout.addWidget(self.button)
        return frame

    def mapTypeToResult(self, type_: FlowRecordType):
        if type_ == FlowRecordType.VALID:
            return self.tr("有效")
        elif type_ == FlowRecordType.INVALID:
            return self.tr("无效")
        elif type_ == FlowRecordType.REPEATED:
            return self.tr("重复")
        else:
            return self.tr("未知")

    def setTableContent(self, record: typing.List[AttendanceFlow]):
        self.tableWidget.clearContents()
        for i in range(min(self.tableWidget.rowCount(), len(record))):
            self.tableWidget.setItem(i, 0, QTableWidgetItem(record[i].water_time))
            self.tableWidget.setItem(i, 1, QTableWidgetItem(record[i].place))
            statusWidget = QTableWidgetItem(self.mapTypeToResult(record[i].type_))
            if record[i].type_ == FlowRecordType.INVALID:
                statusWidget.setForeground(Color.INVALID_COLOR)
            elif record[i].type_ == FlowRecordType.REPEATED:
                statusWidget.setForeground(Color.REPEAT_COLOR)
            else:
                statusWidget.setForeground(Color.VALID_COLOR)
            self.tableWidget.setItem(i, 2, statusWidget)

    def constructWithAccountFrame(self) -> QFrame:
        frame = QFrame(self)
        vBoxLayout = VBoxLayout(frame)
        self.commandBar = CommandBar(self)
        vBoxLayout.addWidget(self.commandBar)
        self.commandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.webVPNLoginAction = Action(FluentIcon.APPLICATION, self.tr("登录 WebVPN"))
        self.webVPNLoginAction.triggered.connect(self.onWebVPNLoginClicked)
        self.commandBar.addAction(self.webVPNLoginAction)
        self.normalLoginAction = Action(FluentIcon.DOCUMENT, self.tr("直接登录"))
        self.commandBar.addAction(self.normalLoginAction)
        self.normalLoginAction.triggered.connect(self.onNormalLoginClicked)
        self.commandBar.addSeparator()
        self.refreshAction = Action(FluentIcon.SYNC, self.tr("立刻刷新"))
        self.refreshAction.triggered.connect(self.onSearchClicked)
        self.commandBar.addAction(self.refreshAction)
        self.prevAction = Action(FluentIcon.UP, self.tr("上一页"))
        self.prevAction.triggered.connect(self.onPrevClicked)
        self.commandBar.addAction(self.prevAction)
        self.nextAction = Action(FluentIcon.DOWN, self.tr("下一页"))
        self.nextAction.triggered.connect(self.onNextClicked)
        self.commandBar.addAction(self.nextAction)

        self.thread_ = AttendanceFlowThread(accounts.current, choice=None, page=1, size=5,
                                            parent=self)
        self.processWidget = ProcessWidget(thread=self.thread_,stoppable=True)
        vBoxLayout.addWidget(self.processWidget)
        self.processWidget.canceled.connect(self.onThreadTerminated, Qt.UniqueConnection)
        self.processWidget.setVisible(False)

        self.tableWidget = TableWidget(self)
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setRowCount(5)
        self.tableWidget.setHorizontalHeaderItem(0, QTableWidgetItem(self.tr("考勤时间")))
        self.tableWidget.setHorizontalHeaderItem(1, QTableWidgetItem(self.tr("教室")))
        self.tableWidget.setHorizontalHeaderItem(2, QTableWidgetItem(self.tr("是否有效")))
        self.tableWidget.setColumnWidth(0, 200)
        self.tableWidget.setColumnWidth(1, 120)
        self.tableWidget.setColumnWidth(2, 70)
        self.tableWidget.setMinimumSize(430, 250)
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # self.tableWidget.setMinimumSize(550, 250)
        vBoxLayout.addWidget(self.tableWidget, stretch=1, alignment=Qt.AlignHCenter)

        self.pager = PipsPager(Qt.Horizontal)

        # 始终显示前进和后退按钮
        self.pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self.pager.setVisible(False)
        self.pager.currentIndexChanged.connect(self.onPageClicked)

        vBoxLayout.addWidget(self.pager, alignment=Qt.AlignHCenter)

        self.mentionLabel = BodyLabel(
            self.tr("使用说明：先点击「登录 WebVPN」或者「直接登录」，然后选择「立刻刷新」即可查询\n"
                    "结果说明：有效：正常上课刷卡；无效：没有课却刷了卡；重复：正常上课刷了多次卡"),
            frame
        )
        vBoxLayout.addWidget(self.mentionLabel, alignment=Qt.AlignHCenter)

        return frame


class AttendanceInterface(ScrollArea):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("attendanceInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")

        # 初始化标题
        self.vBoxLayout = VBoxLayout(self.view)

        # 初始化多选栏
        self.pivot = Pivot(self)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout.addWidget(self.pivot, 0, Qt.AlignHCenter)

        self.vBoxLayout.addWidget(self.stackedWidget, 1, Qt.AlignHCenter)
        self.vBoxLayout.setContentsMargins(30, 20, 30, 30)

        self.stackedWidget.currentChanged.connect(self.onCurrentIndexChanged)

        # 初始化子界面：考勤流水
        self.flowWidget = AttendanceFlowWidget(main_window, self)
        self.addSubInterface(self.flowWidget, "flowWidget", self.tr("考勤流水"))

        self.stackedWidget.setCurrentWidget(self.flowWidget)
        self.pivot.setCurrentItem(self.stackedWidget.objectName())

        # 设置 ScrollArea 并使用样式表
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        StyleSheet.ATTENDANCE_INTERFACE.apply(self)

    def addSubInterface(self, widget, objectName, text):
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(
            routeKey=objectName,
            text=text,
            onClick=lambda: self.stackedWidget.setCurrentWidget(widget)
        )

    def onCurrentIndexChanged(self, index):
        widget = self.stackedWidget.widget(index)
        self.pivot.setCurrentItem(widget.objectName())
