import typing

from PyQt5.QtWidgets import QWidget, QStackedWidget, QTableWidgetItem, QFrame, QHeaderView, QAbstractItemView
from PyQt5.QtCore import Qt, pyqtSlot
from qfluentwidgets import ScrollArea, VBoxLayout, Pivot, BodyLabel, PrimaryPushButton, TableWidget, \
    CommandBar, Action, FluentIcon, InfoBar, InfoBarPosition
from .utils import StyleSheet, accounts, AccountCacheManager
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

        self.page_added = False

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

    @pyqtSlot()
    def currentAccountChanged(self):
        self.clearTableContent()
        self.thread_.account = accounts.current
        self.thread_.reset()
        self.loadContentCache()

    @pyqtSlot()
    def lock(self):
        """锁定一切网络连接有关的元素"""
        self.webVPNLoginAction.setEnabled(False)
        self.normalLoginAction.setEnabled(False)
        self.refreshAction.setEnabled(False)
        self.nextAction.setEnabled(False)
        self.prevAction.setEnabled(False)

    @pyqtSlot()
    def unlock(self):
        """解锁一切网络连接有关的元素"""
        self.webVPNLoginAction.setEnabled(True)
        self.normalLoginAction.setEnabled(True)
        self.refreshAction.setEnabled(True)
        self.nextAction.setEnabled(True)
        self.prevAction.setEnabled(True)

    @pyqtSlot()
    def onWebVPNLoginClicked(self):
        self.processWidget.setVisible(True)
        self.thread_.choice = AttendanceFlowChoice.WEBVPN_LOGIN
        self.lock()
        self.thread_.start()

    @pyqtSlot()
    def onNormalLoginClicked(self):
        self.processWidget.setVisible(True)
        self.thread_.choice = AttendanceFlowChoice.NORMAL_LOGIN
        self.lock()
        self.thread_.start()

    @pyqtSlot()
    def onSearchClicked(self):
        self.processWidget.setVisible(True)
        self.thread_.choice = AttendanceFlowChoice.SEARCH
        self.lock()
        self.thread_.start()

    @pyqtSlot()
    def onNextClicked(self):
        self.page_added = True
        self.thread_.page += 1
        self.onSearchClicked()

    @pyqtSlot()
    def onPrevClicked(self):
        if self.thread_.page > 1:
            self.thread_.page -= 1
            self.onSearchClicked()
        else:
            InfoBar.success("", self.tr("已经到顶啦"), duration=2000, position=InfoBarPosition.TOP_RIGHT,
                            parent=self._parent)

    @pyqtSlot(list)
    def onGetFlowRecord(self, record: list):
        self.setTableContent(record)
        self.saveContentCache(record)

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
        InfoBar.success(self.tr("登录成功"), msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=self._parent)
        self.page_added = False

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        InfoBar.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self._parent)
        # 保存是否增加了页面数；如果增加了，则减少回去，以免出现“取消了但是页面数还是增加了”的情况
        if self.page_added:
            self.thread_.page -= 1 if self.thread_.page > 1 else 0
            self.page_added = False

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
        for i in range(min(self.tableWidget.rowCount(), len(record))):
            self.tableWidget.setItem(i, 0, QTableWidgetItem(record[i].water_time))
            self.tableWidget.setItem(i, 1, QTableWidgetItem(record[i].place))
            self.tableWidget.setItem(i, 2, QTableWidgetItem(self.mapTypeToResult(record[i].type_)))

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
        self.processWidget = ProcessWidget(thread=self.thread_)
        vBoxLayout.addWidget(self.processWidget)
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
