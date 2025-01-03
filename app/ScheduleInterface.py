import datetime
import os.path

from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QAbstractItemView, QFrame, QHBoxLayout, QHeaderView
from qfluentwidgets import ScrollArea, TableWidget, CommandBar, Action, FluentIcon, ComboBox, \
    PushButton, InfoBarPosition, InfoBar, MessageBox

from app.components.ScheduleTable import ScheduleTableWidget
from app.threads.ProcessWidget import ProcessWidget
from app.threads.ScheduleAttendanceThread import ScheduleAttendanceThread, AttendanceFlowLogin
from app.threads.ScheduleThread import ScheduleThread
from app.utils import StyleSheet, accounts, cfg
from app.utils.migrate_data import account_data_directory
from attendance.attendance import AttendanceWaterRecord, AttendanceFlow, WaterType, FlowRecordType
from schedule.schedule_database import CourseInstance, CourseStatus
from schedule.schedule_service import ScheduleService


class ScheduleInterface(ScrollArea):
    """课程表界面"""
    def __init__(self, parent=None):
        super().__init__(parent)

        self.view = QWidget(self)
        self.setObjectName("ScheduleInterface")

        self.view.setObjectName("view")

        self._onlyNotice = None
        self.DAYS = [self.tr("周一"), self.tr("周二"), self.tr("周三"), self.tr("周四"), self.tr("周五"), self.tr("周六"), self.tr("周日")]

        self.schedule_service = ScheduleService(os.path.join(account_data_directory(accounts.current), "schedule.db"))\
        if accounts.current else None

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

        self.commandFrame = QFrame(self)
        self.frameLayout = QHBoxLayout(self.commandFrame)
        self.leftCommandBar = CommandBar(self)
        self.leftCommandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.getTableAction = Action(FluentIcon.SYNC, self.tr("获取课表"), self.leftCommandBar)
        self.getTableAction.triggered.connect(self.onGetTableClicked)
        self.leftCommandBar.addAction(self.getTableAction)

        self.lastWeekButton = PushButton('<', parent=self)
        self.lastWeekButton.setFixedWidth(45)
        self.weekComboBox = ComboBox(self)
        self.weekComboBox.addItems([str(i) for i in range(1, 19)])
        self.weekComboBox.currentIndexChanged.connect(self.onWeekChanged)
        self.nextWeekButton = PushButton('>', parent=self)
        self.nextWeekButton.setFixedWidth(45)
        self.nextWeekButton.clicked.connect(self.onNextWeekClicked)
        self.lastWeekButton.clicked.connect(self.onLastWeekClicked)

        self.rightCommandBar = CommandBar(self)
        self.rightCommandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.getWeekAttendanceAction = Action(FluentIcon.DOCUMENT, self.tr("获取本周考勤"), self.rightCommandBar)
        self.getWeekAttendanceAction.triggered.connect(self.onGetWeekAttendanceClicked)
        self.rightCommandBar.addAction(self.getWeekAttendanceAction)

        self.frameLayout.addWidget(self.leftCommandBar, stretch=1)
        self.frameLayout.addWidget(self.lastWeekButton)
        self.frameLayout.addWidget(self.weekComboBox)
        self.frameLayout.addWidget(self.nextWeekButton)
        self.frameLayout.addWidget(self.rightCommandBar, stretch=1)

        self.table_widget = TableWidget(self)
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels(self.DAYS)
        self.table_widget.setRowCount(13)
        self.table_widget.setVerticalHeaderLabels([self.tr("一"), self.tr("二"), self.tr("三"), self.tr("四"), self.tr("午休"),
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

        self.vBoxLayout.addWidget(self.commandFrame)
        self.vBoxLayout.addWidget(self.process_widget_ehall)
        self.vBoxLayout.addWidget(self.process_widget_attendance)
        self.vBoxLayout.addWidget(self.table_widget)

        # 加载可能存在的课表缓存到页面中
        if accounts.current is not None:
            self.loadSchedule()

        StyleSheet.SCHEDULE_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    @property
    def week(self):
        return self.weekComboBox.currentIndex() + 1

    def getCurrentWeek(self):
        """
        获取当前周数，如果学期开始时间为空，则返回 1，不会超过 18 周
        :return: 周数
        """
        start = self.schedule_service.getStartOfTerm()
        if start is None:
            return 1
        current = datetime.date.today()
        return min((current - start).days // 7 + 1, 18)

    @pyqtSlot(int)
    def onWeekChanged(self, week: int):
        """
        当周数改变时，加载新的课程表
        :param week: 新的周数
        """
        self.loadSchedule(week + 1)

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

    @pyqtSlot()
    def lock(self):
        """
        锁定一切与网络通信相关的按钮
        """
        self.getTableAction.setEnabled(False)
        self.getWeekAttendanceAction.setEnabled(False)
        self.lastWeekButton.setEnabled(False)
        self.nextWeekButton.setEnabled(False)
        self.weekComboBox.setEnabled(False)
        self.process_widget_attendance.setVisible(False)
        self.process_widget_ehall.setVisible(False)

    @pyqtSlot()
    def unlock(self):
        """
        解锁一切与网络通信相关的按钮
        """
        self.getTableAction.setEnabled(True)
        self.getWeekAttendanceAction.setEnabled(True)
        self.lastWeekButton.setEnabled(True)
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

        # 锁定按钮
        if week == 1:
            self.lastWeekButton.setEnabled(False)
        else:
            self.lastWeekButton.setEnabled(True)
        if week == 18:
            self.nextWeekButton.setEnabled(False)
        else:
            self.nextWeekButton.setEnabled(True)

        # 显示日期和本天特殊颜色
        start_date = self.schedule_service.getStartOfTerm()
        if start_date is not None:
            self.table_widget.setHorizontalHeaderLabels(
                [(start_date + datetime.timedelta(days=(week - 1) * 7 + i)).strftime("%m.%d") + "\t" + self.DAYS[i] for i in range(7)]
            )
            today = datetime.date.today()
            if start_date + datetime.timedelta(days=(week - 1) * 7) <= today < start_date + datetime.timedelta(days=week * 7):
                item = self.table_widget.horizontalHeaderItem(today.weekday())
                item.setText("今天\t" + item.text())

        schedule = self.schedule_service.getCourseInWeek(week)

        for i in range(13):
            for j in range(7):
                self.table_widget.removeCellWidget(i, j)

        for course in schedule:
            # 如果课程的开始时间在第四节课前，说明是上午，放到 start_time - 1 行
            if course.start_time <= 4:
                self.table_widget.setCellWidget(course.start_time - 1, course.day_of_week - 1, ScheduleTableWidget(course))
                self.table_widget.setSpan(course.start_time - 1, course.day_of_week - 1, course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第五节课后，说明是下午，放到 start_time 行（因为有一行午休是不用的）
            elif course.start_time <= 8:
                self.table_widget.setCellWidget(course.start_time, course.day_of_week - 1, ScheduleTableWidget(course))
                self.table_widget.setSpan(course.start_time, course.day_of_week - 1, course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第九节课后，说明是晚上，放到 start_time + 1 行（因为有一行午休+一行晚休共计两行是不用的）
            else:
                self.table_widget.setCellWidget(course.start_time + 1, course.day_of_week - 1, ScheduleTableWidget(course))
                self.table_widget.setSpan(course.start_time + 1, course.day_of_week - 1, course.end_time - course.start_time + 1, 1)
        if schedule:
            self.table_widget.adjustSize()

    @pyqtSlot()
    def onGetTableClicked(self):
        if not self.schedule_service.getCourseInTerm():
            self.process_widget_ehall.setVisible(True)
            self.lock()
            self.schedule_thread.start()
        else:
            w = MessageBox(self.tr("获取课表"), self.tr("获取课表后，所有非手动添加的课程将会清空，是否继续？"), self)
            w.yesButton.setText(self.tr("确定"))
            w.cancelButton.setText(self.tr("取消"))
            if w.exec():
                self.process_widget_ehall.setVisible(True)
                self.lock()
                self.schedule_thread.start()

    @pyqtSlot()
    def onGetWeekAttendanceClicked(self):
        start = self.schedule_service.getStartOfTerm()
        start_date = start + datetime.timedelta(days=(self.week - 1) * 7)
        if start_date > datetime.date.today():
            self.error(self.tr("错误"), self.tr("无法获取未来的考勤记录"))
            return
        end_date = start + datetime.timedelta(days=self.week * 7 - 1)
        if end_date > datetime.date.today():
            end_date = datetime.date.today()

        self.schedule_attendance_thread.start_date = start_date.strftime("%Y-%m-%d")
        self.schedule_attendance_thread.end_date = end_date.strftime("%Y-%m-%d")
        setting = cfg.get(cfg.defaultAttendanceLoginMethod)
        if setting == cfg.AttendanceLoginMethod.WEBVPN:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
        elif setting == cfg.AttendanceLoginMethod.NORMAL:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
        else:
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

    @pyqtSlot(dict)
    def onReceiveSchedule(self, schedule: dict):
        self.schedule_service.clearNonManualCourses()
        # 如果学期编号比当前的大，更新当前学期及其开始时间
        if self.schedule_service.getCurrentTerm() is None or self.schedule_service.getCurrentTerm() < schedule["term_number"]:
            self.schedule_service.setCurrentTerm(schedule["term_number"])
            self.schedule_service.setStartOfTerm(schedule["start_date"])
        # 如果学期编号相同，但开始时间为空，更新开始时间
        if self.schedule_service.getStartOfTerm() is None:
            self.schedule_service.setStartOfTerm(schedule["start_date"])

        for lesson in schedule["lessons"]:
            self.schedule_service.addCourseFromJson(lesson, merge_with_existing=True)
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
            if page.type_ == FlowRecordType.VALID:
                water_time = datetime.datetime.strptime(page.water_time, "%Y-%m-%d %H:%M:%S")
                date = water_time.date()
                week = (water_time.date() - self.schedule_service.getStartOfTerm()).days // 7 + 1
                try:
                    lesson = self.schedule_service.selectCourse(CourseInstance.week_number == week,
                                                                 CourseInstance.day_of_week == date.weekday() + 1,
                                                                 CourseInstance.location == page.place)[0]
                except IndexError:
                    continue
                if lesson.status != CourseStatus.UNKNOWN:
                    continue
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
        # 重载课表服务为当前账户的内容
        self.schedule_service = ScheduleService(os.path.join(account_data_directory(accounts.current), "schedule.db"))
        self.loadSchedule()
