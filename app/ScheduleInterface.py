import datetime
import os.path

from icalendar import Calendar

from PyQt5.QtCore import pyqtSlot, QPoint
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QAbstractItemView, QFrame, QHBoxLayout, QHeaderView
from icalendar.cal import Event
from qfluentwidgets import ScrollArea, TableWidget, ComboBox, \
    PushButton, InfoBarPosition, InfoBar, MessageBox, PrimaryPushButton, TransparentPushButton, RoundMenu, Action, \
    StateToolTip
from qfluentwidgets import FluentIcon as FIF

from app.components.ScheduleTable import ScheduleTableWidget
from app.sub_interfaces.ChangeTermDialog import ChangeTermDialog
from app.sub_interfaces.ExportCalendarDialog import ExportCalendarDialog
from app.sub_interfaces.LessonConflictDialog import LessonConflictDialog
from app.sub_interfaces.LessonDetailDialog import LessonDetailDialog
from app.threads.HolidayThread import HolidayThread
from app.threads.ProcessWidget import ProcessWidget
from app.threads.ScheduleAttendanceMonitorThread import ScheduleAttendanceMonitorThread
from app.threads.ScheduleAttendanceThread import ScheduleAttendanceThread, AttendanceFlowLogin
from app.threads.ScheduleThread import ScheduleThread
from app.utils import StyleSheet, accounts, cfg
from app.utils.cache import cacheManager
from app.utils.migrate_data import account_data_directory
from attendance.attendance import AttendanceWaterRecord, AttendanceFlow, WaterType, FlowRecordType
from schedule import getAttendanceEndTime, getAttendanceStartTime, getClassStartTime, getClassEndTime
from schedule.schedule_database import CourseInstance, CourseStatus
from schedule.schedule_service import ScheduleService
from schedule.xjtu_time import isSummerTime


class ScheduleInterface(ScrollArea):
    """课程表界面"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.view = QWidget(self)
        self.setObjectName("ScheduleInterface")

        self.view.setObjectName("view")

        self._onlyNotice = None
        self.DAYS = [self.tr("周一"), self.tr("周二"), self.tr("周三"), self.tr("周四"), self.tr("周五"),
                     self.tr("周六"), self.tr("周日")]

        self.schedule_service = ScheduleService(os.path.join(account_data_directory(accounts.current), "schedule.db")) \
            if accounts.current else None

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        self.vBoxLayout = QVBoxLayout(self.view)
        self.schedule_thread = ScheduleThread()
        self.schedule_thread.schedule.connect(self.onReceiveSchedule)
        self.schedule_attendance_thread = ScheduleAttendanceThread()
        self.process_widget_ehall = ProcessWidget(self.schedule_thread, stoppable=True)
        self.process_widget_ehall.setVisible(False)
        self.schedule_thread.error.connect(self.onThreadError)
        self.schedule_thread.finished.connect(self.unlock)

        self.process_widget_attendance = ProcessWidget(self.schedule_attendance_thread, stoppable=True)
        self.process_widget_attendance.setVisible(False)
        self.schedule_attendance_thread.result.connect(self.onReceiveAttendance)
        self.schedule_attendance_thread.error.connect(self.onThreadError)
        self.schedule_attendance_thread.finished.connect(self.unlock)

        # 监视线程
        self.schedule_attendance_monitor_thread = ScheduleAttendanceMonitorThread(self.schedule_attendance_thread,
                                                                                  self.process_widget_attendance)
        self.process_widget_attendance.connectMonitorThread(self.schedule_attendance_monitor_thread)
        self.schedule_attendance_monitor_thread.result.connect(self.onReceiveAttendance)

        self.holiday_thread = HolidayThread()
        self.holiday_thread.result.connect(self.onReceiveHoliday)

        self.commandFrame = QFrame(self)
        self.frameLayout = QHBoxLayout(self.commandFrame)

        self.termButton = TransparentPushButton(self)
        self.termButton.setMaximumWidth(150)
        self.termButton.clicked.connect(self.onChangeTermClicked)

        self.getTableButton = PushButton(self.tr("获取课表"), parent=self)
        self.getTablePrimaryButton = PrimaryPushButton(self.tr("获取课表"), parent=self)
        self.getTablePrimaryButton.clicked.connect(self.onGetTableClicked)
        self.getTableButton.clicked.connect(self.onGetTableClicked)

        self.getWeekAttendanceButton = PushButton(self.tr("获取本周考勤"), parent=self)
        self.getWeekAttendanceButton.clicked.connect(self.onGetWeekAttendanceClicked)
        self.getWeekAttendancePrimaryButton = PrimaryPushButton(self.tr("获取本周考勤"), parent=self)
        self.getWeekAttendancePrimaryButton.clicked.connect(self.onGetWeekAttendanceClicked)

        # 作为菜单触发器的按钮
        self.moreButton = TransparentPushButton("更多...", parent=self)
        self.moreButton.setFixedWidth(100)
        self.moreButton.clicked.connect(lambda: self.createMoreMenu(self.moreButton.mapToGlobal(
            QPoint(0, self.moreButton.height()))))

        self.lastWeekButton = PushButton('<', parent=self)
        self.lastWeekButton.setFixedWidth(45)
        self.weekComboBox = ComboBox(self)
        self.weekComboBox.addItems([str(i) for i in range(1, 19)])
        self.weekComboBox.currentIndexChanged.connect(self.onWeekChanged)
        self.weekComboBox.setMaximumWidth(70)
        self.nextWeekButton = PushButton('>', parent=self)
        self.nextWeekButton.setFixedWidth(45)
        self.nextWeekButton.clicked.connect(self.onNextWeekClicked)
        self.lastWeekButton.clicked.connect(self.onLastWeekClicked)

        self.frameLayout.addWidget(self.termButton)
        self.frameLayout.addWidget(self.getTableButton)
        self.frameLayout.addWidget(self.getTablePrimaryButton)
        self.frameLayout.addWidget(self.lastWeekButton)
        self.frameLayout.addWidget(self.weekComboBox)
        self.frameLayout.addWidget(self.nextWeekButton)
        self.frameLayout.addWidget(self.getWeekAttendanceButton)
        self.frameLayout.addWidget(self.getWeekAttendancePrimaryButton)
        self.frameLayout.addWidget(self.moreButton)

        # 更多菜单
        self.moreMenu = RoundMenu(parent=self)
        # 修改学期菜单项
        self.changeTermAction = Action(FIF.EDIT, self.tr("修改学期..."))
        self.moreMenu.addAction(self.changeTermAction)
        self.changeTermAction.triggered.connect(self.onChangeTermClicked)
        # 导出为 ics 菜单项
        self.exportAction = Action(FIF.SHARE, self.tr("导出 ics..."))
        self.moreMenu.addAction(self.exportAction)
        self.exportAction.triggered.connect(self.onExportClicked)
        # 清空课程菜单项
        self.clearAction = Action(FIF.CLOSE, self.tr("清空课程..."))
        self.moreMenu.addAction(self.clearAction)
        self.clearAction.triggered.connect(self.onClearClicked)

        self.stateToolTip = None
        self._export_path = None

        self.table_widget = TableWidget(self)
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels(self.DAYS)
        self.table_widget.setRowCount(13)
        self.table_widget.setVerticalHeaderLabels(
            [self.tr("一"), self.tr("二"), self.tr("三"), self.tr("四"), self.tr("午休"),
             self.tr("五"), self.tr("六"), self.tr("七"), self.tr("八"), self.tr("晚休"),
             self.tr("九"), self.tr("十"), self.tr("十一")])
        self.table_widget.setSpan(4, 0, 1, 7)
        self.table_widget.setSpan(9, 0, 1, 7)
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_widget.setSelectionMode(QAbstractItemView.NoSelection)
        for day in range(7):
            self.table_widget.setSpan(0, day, 2, 1)
            self.table_widget.setSpan(2, day, 2, 1)
            self.table_widget.setSpan(5, day, 2, 1)
            self.table_widget.setSpan(7, day, 2, 1)
            self.table_widget.setSpan(10, day, 2, 1)
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.horizontalHeader().setMinimumSectionSize(50)

        # 去除悬浮时高亮一行的效果，否则和合并的单元格放在一起很难看
        self.table_widget.entered.disconnect()
        self.table_widget.leaveEvent = lambda _: None

        self.table_widget.cellClicked.connect(self.onCellClicked)

        self.detailDialog = None

        self.vBoxLayout.addWidget(self.commandFrame)
        self.vBoxLayout.addWidget(self.process_widget_ehall)
        self.vBoxLayout.addWidget(self.process_widget_attendance)
        self.vBoxLayout.addWidget(self.table_widget)

        # 加载可能存在的课表缓存到页面中
        if accounts.current is not None:
            if self.schedule_service.getStartOfTerm() is not None:
                self.loadSchedule()
                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
            else:
                term = self.schedule_service.getCurrentTerm()
                if term is not None:
                    self.termButton.setText(self.schedule_service.getCurrentTerm())

                self.setTablePrimary(True)
                self.setAttendancePrimary(False)
        else:
            self.termButton.setText(self.tr("未登录"))
            self.setTablePrimary(False)
            self.setAttendancePrimary(False)

        StyleSheet.SCHEDULE_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def setTablePrimary(self, primary: bool):
        self.getTablePrimaryButton.setVisible(primary)
        self.getTableButton.setVisible(not primary)

    def setAttendancePrimary(self, primary: bool):
        self.getWeekAttendancePrimaryButton.setVisible(primary)
        self.getWeekAttendanceButton.setVisible(not primary)

    def setTableEnabled(self, enabled: bool):
        self.getTableButton.setEnabled(enabled)
        self.getTablePrimaryButton.setEnabled(enabled)

    def setAttendanceEnabled(self, enabled: bool):
        self.getWeekAttendanceButton.setEnabled(enabled)
        self.getWeekAttendancePrimaryButton.setEnabled(enabled)

    def createMoreMenu(self, position):
        self.moreMenu.exec(position, ani=True)

    @property
    def week(self):
        return self.weekComboBox.currentIndex() + 1

    def getCurrentWeek(self):
        """
        获取当前周数，如果学期开始时间为空或大于当前日期，或者当前日期超过了学期结束时间，则返回 1。结果不会超过 18 周
        :return: 周数
        """
        start = self.schedule_service.getStartOfTerm()
        current = datetime.date.today()
        if start is None or start > current or (current - start).days // 7 >= 20:
            return 1
        return min((current - start).days // 7 + 1, 18)

    @pyqtSlot(int)
    def onWeekChanged(self, week: int):
        """
        当周数改变时，加载新的课程表
        :param week: 新的周数
        """
        if self.schedule_service is not None:
            self.loadSchedule(week + 1)
        else:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)

    @pyqtSlot()
    def onNextWeekClicked(self):
        """
        下一周按钮点击事件
        """
        current = self.weekComboBox.currentIndex()
        if current < 17:
            self.weekComboBox.setCurrentIndex(current + 1)

    @pyqtSlot()
    def onLastWeekClicked(self):
        """
        上一周按钮点击事件
        """
        current = self.weekComboBox.currentIndex()
        if current > 0:
            self.weekComboBox.setCurrentIndex(current - 1)

    @pyqtSlot(CourseInstance)
    def onLessonDetailClicked(self, course):
        """
        课程详情按钮点击事件
        """
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return
        start = self.schedule_service.getStartOfTerm()
        if start is None:
            self.error("", self.tr("请先获取课表"), parent=self)
            return
        # 更新最新的信息
        course = CourseInstance.get_by_id(course.id)
        self.detailDialog = LessonDetailDialog(course, start, self, self)
        self.detailDialog.rejected.connect(self.onCourseInfoFinished)
        self.detailDialog.exec()

    @pyqtSlot(int, int)
    def onCellClicked(self, row, column):
        cell_widget = self.table_widget.cellWidget(row, column)
        # 忽略午休和晚休的点击
        if row == 4 or row == 9 or row == 12:
            return
        if cell_widget is not None:
            return
        else:
            if row < 4:
                start_time = row + 1
            elif row < 9:
                start_time = row
            else:
                start_time = row - 1
            start_date = self.schedule_service.getStartOfTerm()
            self.detailDialog = LessonDetailDialog(self.week, column + 1, start_time, start_time + 1, start_date, self, self)
            self.detailDialog.rejected.connect(self.onCourseInfoFinished)
            self.detailDialog.exec()

    @pyqtSlot()
    def onCourseInfoFinished(self):
        if self.detailDialog.modified:
            # 这个写法虽然很奇怪，但是直接调用 loadSchedule 会导致课程表大小变得很小，不知道为什么
            # 这样做就没有问题
            self.weekComboBox.setCurrentIndex(self.weekComboBox.currentIndex() + 1)
            self.weekComboBox.setCurrentIndex(self.weekComboBox.currentIndex() - 1)

    def getSameCourseInOtherWeek(self, course):
        if self.schedule_service is None:
            return None
        else:
            return self.schedule_service.getSameCourseInOtherWeek(course)

    @pyqtSlot()
    def lock(self):
        """
        锁定一切与网络通信相关的按钮
        """
        self.getTableButton.setEnabled(False)
        self.getWeekAttendanceButton.setEnabled(False)
        self.getTablePrimaryButton.setEnabled(False)
        self.getWeekAttendancePrimaryButton.setEnabled(False)
        self.lastWeekButton.setEnabled(False)
        self.nextWeekButton.setEnabled(False)
        self.weekComboBox.setEnabled(False)

    @pyqtSlot()
    def unlock(self):
        """
        解锁一切与网络通信相关的按钮
        """
        self.getTableButton.setEnabled(True)
        self.getWeekAttendanceButton.setEnabled(True)
        self.getTablePrimaryButton.setEnabled(True)
        self.getWeekAttendancePrimaryButton.setEnabled(True)
        if self.week > 1:
            self.lastWeekButton.setEnabled(True)
        if self.week < 18:
            self.nextWeekButton.setEnabled(True)
        self.weekComboBox.setEnabled(True)
        self.process_widget_attendance.setVisible(False)
        self.process_widget_ehall.setVisible(False)

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

    def warning(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个警告的通知。如果已经存在通知，已存在的通知会被立刻关闭。
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
        self._onlyNotice = InfoBar.warning(title, msg, duration=duration, position=position, parent=parent)

    @pyqtSlot(str)
    def onThreadSuccess(self, msg):
        self.success(self.tr("成功"), msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    def loadSchedule(self, week=None):
        """
        加载某一周的课程表到页面中
        :param week: 周数
        """
        if week is None:
            week = self.getCurrentWeek()
        # 设置当前周数为加载的周数
        if self.weekComboBox.currentIndex() != week - 1:
            self.weekComboBox.setCurrentIndex(week - 1)

        self.termButton.setText(self.schedule_service.getCurrentTerm())

        # 锁定按钮
        if week == 1:
            self.lastWeekButton.setEnabled(False)
        else:
            self.lastWeekButton.setEnabled(True)
        if week == 18:
            self.nextWeekButton.setEnabled(False)
        else:
            self.nextWeekButton.setEnabled(True)

        # 重置表头
        self.table_widget.setHorizontalHeaderLabels(self.DAYS)

        # 显示日期和本天特殊颜色
        start_date = self.schedule_service.getStartOfTerm()
        if start_date is not None:
            self.table_widget.setHorizontalHeaderLabels(
                [(start_date + datetime.timedelta(days=(week - 1) * 7 + i)).strftime("%m.%d") + "\t" + self.DAYS[i] for
                 i in range(7)]
            )
            today = datetime.date.today()
            if start_date + datetime.timedelta(days=(week - 1) * 7) <= today < start_date + datetime.timedelta(
                    days=week * 7):
                item = self.table_widget.horizontalHeaderItem(today.weekday())
                item.setText("今天\t" + item.text())

        schedule = self.schedule_service.getCourseInWeek(week)

        for i in range(13):
            for j in range(7):
                widget = self.table_widget.cellWidget(i, j)
                if widget is not None:
                    widget.clicked.disconnect()
                self.table_widget.removeCellWidget(i, j)

        for course in schedule:
            widget = ScheduleTableWidget(course)
            widget.clicked.connect(self.onLessonDetailClicked)
            # 如果课程的开始时间在第四节课前，说明是上午，放到 start_time - 1 行
            if course.start_time <= 4:
                self.table_widget.setCellWidget(course.start_time - 1, course.day_of_week - 1, widget)
                self.table_widget.setSpan(course.start_time - 1, course.day_of_week - 1,
                                          course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第五节课后，说明是下午，放到 start_time 行（因为有一行午休是不用的）
            elif course.start_time <= 8:
                self.table_widget.setCellWidget(course.start_time, course.day_of_week - 1, widget)
                self.table_widget.setSpan(course.start_time, course.day_of_week - 1,
                                          course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第九节课后，说明是晚上，放到 start_time + 1 行（因为有一行午休+一行晚休共计两行是不用的）
            else:
                self.table_widget.setCellWidget(course.start_time + 1, course.day_of_week - 1, widget)
                self.table_widget.setSpan(course.start_time + 1, course.day_of_week - 1,
                                          course.end_time - course.start_time + 1, 1)
        if schedule:
            self.table_widget.adjustSize()

        # 根据这学期是否有课程，设置按钮是否高亮
        if self.schedule_service.getCourseInTerm():
            self.setTablePrimary(False)
            self.setAttendancePrimary(True)
        else:
            self.setTablePrimary(True)
            self.setAttendancePrimary(False)

    @pyqtSlot()
    def onGetTableClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        term_number = self.schedule_service.getCurrentTerm()
        self.schedule_thread.term_number = term_number
        if not self.schedule_service.getCourseInTerm(term_number):
            self.process_widget_ehall.setVisible(True)
            self.lock()
            self.schedule_thread.start()
        else:
            w = MessageBox(self.tr("获取课表"), self.tr("获取课表后，所有非手动添加的课程及其考勤状态将会清空，是否继续？"), self)
            w.yesButton.setText(self.tr("确定"))
            w.cancelButton.setText(self.tr("取消"))
            if w.exec():
                self.process_widget_ehall.setVisible(True)
                self.lock()
                self.schedule_thread.start()

    @pyqtSlot()
    def onGetWeekAttendanceClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        start = self.schedule_service.getStartOfTerm()
        if start is None:
            self.error("", self.tr("请先获取课表"), parent=self)
            return

        start_date = start + datetime.timedelta(days=(self.week - 1) * 7)
        if start_date > datetime.date.today():
            self.error("", self.tr("无法获取未来的考勤记录"), parent=self)
            return
        end_date = start + datetime.timedelta(days=self.week * 7 - 1)
        if end_date > datetime.date.today():
            end_date = datetime.date.today()

        term_number = self.schedule_service.getCurrentTerm()
        self.schedule_attendance_thread.term_number = term_number

        self.schedule_attendance_thread.start_date = start_date.strftime("%Y-%m-%d")
        self.schedule_attendance_thread.end_date = end_date.strftime("%Y-%m-%d")
        setting = cfg.get(cfg.defaultAttendanceLoginMethod)
        if setting == cfg.AttendanceLoginMethod.WEBVPN:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
        elif setting == cfg.AttendanceLoginMethod.NORMAL:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
        else:
            if not self.schedule_attendance_thread.session.has_login:
                w = MessageBox(self.tr("获取考勤"), self.tr("您想使用什么方式登录考勤系统？"), self)
                w.yesButton.setText(self.tr("WebVPN 登录"))
                w.cancelButton.setText(self.tr("直接登录"))
                if w.exec():
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
                else:
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
        self.lock()
        self.process_widget_attendance.setVisible(True)
        self.schedule_attendance_thread.start()
        self.schedule_attendance_monitor_thread.start()

    @pyqtSlot()
    def onChangeTermClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        w = ChangeTermDialog(self)
        if w.exec():
            self.schedule_service.setCurrentTerm(w.term_number)
            self.loadSchedule()

    @pyqtSlot()
    def onClearClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        w = MessageBox(self.tr("清空课程"), self.tr("是否清空本学期所有的课程及其考勤记录？"), self)
        w.yesButton.setText(self.tr("确定"))
        w.cancelButton.setText(self.tr("取消"))
        if w.exec():
            self.schedule_service.clearAllCourses()
            self.setTablePrimary(True)
            self.setAttendancePrimary(False)
            self.loadSchedule()

    @pyqtSlot()
    def onExportClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        w = ExportCalendarDialog(self)
        if w.exec():
            if os.path.exists(os.path.dirname(w.result_path)) and not os.path.isdir(w.result_path):
                self.exportICS(w.result_path, w.ignore_holiday)
            else:
                self.error("", self.tr("导出位置不存在"), parent=self)

    def exportICS(self, path, ignore_holiday=True):
        """
        导出课程表为 ics 文件
        :param path: 导出路径
        :param ignore_holiday: 是否忽略节假日
        """
        self._export_path = path
        if ignore_holiday:
            ignore_data = cacheManager.read_expire_json("ignore_holiday.json", 7)
            if ignore_data is not None:
                for i in range(len(ignore_data)):
                    ignore_data[i] = datetime.datetime.strptime(ignore_data[i], "%Y-%m-%d").date()
            else:
                self.stateToolTip = StateToolTip(self.tr("正在获取节假日信息..."), self.tr("请稍等..."), self)
                self.stateToolTip.move(self.stateToolTip.getSuitablePos())
                self.stateToolTip.show()
                self.holiday_thread.start()
                return

        else:
            ignore_data = []

        self.export(path, ignore_data)

    @pyqtSlot(list)
    def onReceiveHoliday(self, data: list):
        if self.stateToolTip is not None:
            self.stateToolTip.setState(True)
            self.stateToolTip.setContent(self.tr("获取节假日成功"))
            self.stateToolTip = None

        write_data = []
        for one_date in data:
            write_data.append(one_date.strftime("%Y-%m-%d"))
        cacheManager.write_expire_json("ignore_holiday.json", write_data, True)
        self.export(self._export_path, data)

    def export(self, path, ignore_holidays: list[datetime.date]):
        """
        内部函数，实际实现导出功能
        :param path: 导出目标的路径
        :param ignore_holidays: 需要忽略的节假日日期
        :return:
        """
        term_start = self.schedule_service.getStartOfTerm()
        if term_start is None:
            raise ValueError("学期开始时间为空")

        cal = Calendar()

        for course in self.schedule_service.getCourseInTerm():
            e = Event()
            e.add(
                "description",
                '课程名称：' + course.name +
                ';上课地点：' + course.location
            )
            e.add('summary', course.name + '@' + course.location)

            term_start_time = datetime.datetime(term_start.year, term_start.month, term_start.day)
            date = term_start_time + datetime.timedelta(days=(course.week_number - 1) * 7 + course.day_of_week - 1)
            if date.date() in ignore_holidays:
                continue

            begin_time = getClassStartTime(course.start_time, isSummerTime(date))
            end_time = getClassEndTime(course.end_time, isSummerTime(date))

            e.add(
                "dtstart",
                date.replace(
                    hour=begin_time.hour,
                    minute=begin_time.minute
                )
            )
            e.add(
                "dtend",
                date.replace(
                    hour=end_time.hour,
                    minute=end_time.minute
                )
            )
            cal.add_component(e)
        with open(path, "wb") as f:
            f.write(cal.to_ical())

        self.success(self.tr("成功"), self.tr("导出日历成功"), parent=self)

    def checkCourse(self, course1, course2):
        return course1.day_of_week == course2.day_of_week and course1.start_time == course2.start_time and course1.end_time == course2.end_time\
               and course1.name == course2.name

    @pyqtSlot(dict)
    def onReceiveSchedule(self, schedule: dict):
        # 清除获取的新课表所在学期的所有非手动添加的课程
        self.schedule_service.setTermInfo(schedule["term_number"], schedule["start_date"], True)
        self.schedule_service.clearNonManualCourses()

        conflicts = []
        new_courses = []
        for lesson in schedule["lessons"]:
            new_courses.append(self.schedule_service.getCourseGroupFromJson(lesson, manual=False))

        for one_course in new_courses:
            old_course = self.schedule_service.getCourseGroupInCertainTime(one_course.day_of_week, one_course.start_time,
                                                                           one_course.end_time, one_course.term_number)
            if old_course:
                old_course = list(old_course)[0]
                if isinstance(old_course.week_numbers, int):
                    old_course.week_numbers = [old_course.week_numbers]
                else:
                    old_course.week_numbers = old_course.week_numbers.split(",")
                    old_course.week_numbers = [int(i) for i in old_course.week_numbers]

                for week in old_course.week_numbers[:]:
                    if week not in one_course.week_numbers:
                        old_course.week_numbers.remove(week)

                if old_course.week_numbers:
                    # 左侧为新的课程，右侧为已有的冲突课程
                    conflicts.append((one_course, old_course))

        if conflicts:
            conflict_dialog = LessonConflictDialog(conflicts, self)
            if conflict_dialog.exec():
                for index, one_result in enumerate(conflict_dialog.selection):
                    if one_result:
                        # 删除已有的课程
                        self.schedule_service.deleteCourseFromGroup(conflicts[index][1])
                    else:
                        new_course = None
                        for course in new_courses:
                            if self.checkCourse(course, conflicts[index][0]):
                                new_course = course
                                break
                        for one_week in conflicts[index][1].week_numbers:
                            new_course.week_numbers.remove(one_week)
                for course in new_courses:
                    if not course.week_numbers:
                        continue
                    course.manual = 0
                    self.schedule_service.addCourseFromGroup(course, merge_with_existing=True)

                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
                self.loadSchedule()
            else:
                # 取消合并，那么就不添加新获取的课程了
                return

        else:
            for lesson in schedule["lessons"]:
                self.schedule_service.addCourseFromJson(lesson, merge_with_existing=True, manual=False)

        self.setTablePrimary(False)
        self.setAttendancePrimary(True)
        self.loadSchedule()

    @pyqtSlot(list, list)
    def onReceiveAttendance(self, records: list[AttendanceWaterRecord], water_page: list[AttendanceFlow]):
        updated = []
        for record in records:
            try:
                lesson = self.schedule_service.selectCourse(CourseInstance.week_number == record.week,
                                                            CourseInstance.day_of_week == record.date.weekday() + 1,
                                                            CourseInstance.start_time == record.start_time,
                                                            CourseInstance.end_time == record.end_time,
                                                            CourseInstance.term_number == record.term_string)[0]
            except IndexError:
                continue
            if record.status == WaterType.NORMAL:
                lesson.status = CourseStatus.NORMAL.value
            elif record.status == WaterType.LATE:
                lesson.status = CourseStatus.LATE.value
            elif record.status == WaterType.ABSENCE:
                lesson.status = CourseStatus.ABSENT.value
            elif record.status == WaterType.LEAVE:
                lesson.status = CourseStatus.LEAVE.value
            lesson.save()
            updated.append(lesson)

        for page in water_page:
            # 不管是有效的还是重复的，都说明这门课已经打卡了
            if page.type_ == FlowRecordType.VALID or page.type_ == FlowRecordType.REPEATED:
                water_time = datetime.datetime.strptime(page.water_time, "%Y-%m-%d %H:%M:%S")
                date = water_time.date()
                week = (water_time.date() - self.schedule_service.getStartOfTerm()).days // 7 + 1
                lessons = self.schedule_service.selectCourse(CourseInstance.week_number == week,
                                                             CourseInstance.day_of_week == date.weekday() + 1,
                                                             CourseInstance.location == page.place)
                for lesson in lessons:
                    # 如果这门课程已经查询到了考勤状态，就不更新打卡状态
                    if lesson.status != CourseStatus.UNKNOWN.value:
                        continue
                    # 比较打卡流水时间是否在考勤时间内
                    if getAttendanceStartTime(lesson.start_time,
                                              isSummerTime(date)) <= water_time.time() <= getAttendanceEndTime(
                            lesson.start_time, isSummerTime(date)):
                        lesson.status = CourseStatus.CHECKED.value
                        lesson.save()
                        updated.append(lesson)

        for i in range(7):
            for j in range(13):
                widget: ScheduleTableWidget = self.table_widget.cellWidget(j, i)
                if widget is not None:
                    for lesson in updated:
                        if lesson.get_id() == widget.course.get_id():
                            widget.setCourseStatus(lesson.status, save=False)

        self.success(self.tr("成功"), self.tr("获取考勤记录成功"), parent=self)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        if accounts.current is None:
            self.schedule_service = None
            self.table_widget.clear()
            self.setTablePrimary(False)
            self.setAttendancePrimary(False)
        else:
            # 重载课表服务为当前账户的内容
            self.schedule_service = ScheduleService(
                os.path.join(account_data_directory(accounts.current), "schedule.db"))
            if self.schedule_service.getStartOfTerm() is not None:
                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
            else:
                self.setTablePrimary(True)
                self.setAttendancePrimary(False)
            self.loadSchedule()
