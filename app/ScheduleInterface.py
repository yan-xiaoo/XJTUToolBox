import datetime
import os.path
import pytz

from icalendar import Calendar, Alarm

from PyQt5.QtCore import pyqtSlot, QPoint
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QAbstractItemView, QFrame, QHBoxLayout, QHeaderView
from icalendar.cal import Event
from qfluentwidgets import ScrollArea, TableWidget, ComboBox, \
    PushButton, InfoBarPosition, InfoBar, MessageBox, PrimaryPushButton, TransparentPushButton, RoundMenu, Action, \
    StateToolTip
from qfluentwidgets import FluentIcon as FIF

from .components.ScheduleTable import ScheduleTableWidget
from .sessions.attendance_session import AttendanceSession
from .sub_interfaces.ChangeTermDialog import ChangeTermDialog
from .sub_interfaces.ExportCalendarDialog import ExportCalendarDialog
from .sub_interfaces.LessonConflictDialog import LessonConflictDialog
from .sub_interfaces.LessonDetailDialog import LessonDetailDialog
from .sub_interfaces.TermStartTimeDialog import TermStartTimeDialog
from .threads.ExamScheduleThread import ExamScheduleThread
from .threads.GraduateScheduleThread import GraduateScheduleThread
from .threads.HolidayThread import HolidayThread
from .threads.ProcessWidget import ProcessWidget
from .threads.ScheduleAttendanceMonitorThread import ScheduleAttendanceMonitorThread
from .threads.ScheduleAttendanceThread import ScheduleAttendanceThread, AttendanceFlowLogin
from .threads.ScheduleThread import ScheduleThread
from .utils import StyleSheet, accounts, cfg
from .utils.cache import cacheManager
from .utils.migrate_data import account_data_directory
from attendance.attendance import AttendanceWaterRecord, AttendanceFlow, WaterType, FlowRecordType
from schedule import getAttendanceEndTime, getAttendanceStartTime, getClassStartTime, getClassEndTime
from schedule.schedule_database import CourseInstance, CourseStatus, Exam
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
        self.DAYS = [
            self.tr("周一"),
            self.tr("周二"),
            self.tr("周三"),
            self.tr("周四"),
            self.tr("周五"),
            self.tr("周六"),
            self.tr("周日")
        ]

        if accounts.current:
        # 1. 获取目标文件夹路径
            db_dir = account_data_directory(accounts.current)
    
        # 2. 强制创建文件夹（解决 Linux 下找不到路径的问题）
            os.makedirs(db_dir, exist_ok=True)
    
        # 3. 拼接完整路径并初始化数据库服务
            db_path = os.path.join(db_dir, "schedule.db")
            self.schedule_service = ScheduleService(db_path)
        else:
        # 如果没有当前账号，则保持为空
            self.schedule_service = None

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        self.vBoxLayout = QVBoxLayout(self.view)
        self.schedule_thread = ScheduleThread()
        self.schedule_thread.schedule.connect(self.onReceiveSchedule)
        self.schedule_thread.exam.connect(self.onReceiveExam)
        self.schedule_attendance_thread = ScheduleAttendanceThread()
        self.schedule_exam_thread = ExamScheduleThread()
        self.process_widget_ehall = ProcessWidget(self.schedule_thread,
                                                  stoppable=True)
        self.process_widget_ehall.setVisible(False)
        self.schedule_thread.error.connect(self.onThreadError)
        self.schedule_thread.finished.connect(self.unlock)

        self.graduate_schedule_thread = GraduateScheduleThread()
        self.graduate_schedule_thread.schedule.connect(self.onReceiveSchedule)
        self.process_widget_graduate_schedule = ProcessWidget(self.graduate_schedule_thread, stoppable=True)
        self.process_widget_graduate_schedule.setVisible(False)
        self.graduate_schedule_thread.error.connect(self.onThreadError)
        self.graduate_schedule_thread.finished.connect(self.unlock)

        self.process_widget_attendance = ProcessWidget(
            self.schedule_attendance_thread, stoppable=True, backward_animation=False)
        self.process_widget_attendance.setVisible(False)
        self.schedule_attendance_thread.result.connect(
            self.onReceiveAttendance)
        self.schedule_attendance_thread.error.connect(self.onThreadError)
        self.schedule_attendance_thread.finished.connect(self.unlock)

        self.process_widget_exam = ProcessWidget(self.schedule_exam_thread, stoppable=True)
        self.process_widget_exam.setVisible(False)
        self.schedule_exam_thread.error.connect(self.onThreadError)
        self.schedule_exam_thread.finished.connect(self.unlock)
        self.schedule_exam_thread.exam.connect(self.onReceiveExam)

        # 监视线程
        self.schedule_attendance_monitor_thread = ScheduleAttendanceMonitorThread(
            self.schedule_attendance_thread, self.process_widget_attendance)
        self.process_widget_attendance.connectMonitorThread(
            self.schedule_attendance_monitor_thread)
        self.schedule_attendance_monitor_thread.result.connect(
            self.onReceiveAttendance)

        self.holiday_thread = HolidayThread()
        self.holiday_thread.result.connect(self.onReceiveHoliday)
        self.holiday_thread.error.connect(self.onHolidayError)

        self.commandFrame = QFrame(self)
        self.frameLayout = QHBoxLayout(self.commandFrame)

        self.termButton = TransparentPushButton(self)
        self.termButton.setMaximumWidth(150)
        self.termButton.clicked.connect(self.onChangeTermClicked)

        self.getTableButton = PushButton(self.tr("获取课表"), parent=self)
        self.getTablePrimaryButton = PrimaryPushButton(self.tr("获取课表"),
                                                       parent=self)
        self.getTablePrimaryButton.clicked.connect(self.onGetTableClicked)
        self.getTableButton.clicked.connect(self.onGetTableClicked)

        self.getWeekAttendanceButton = PushButton(self.tr("获取本周考勤"),
                                                  parent=self)
        self.getWeekAttendanceButton.clicked.connect(
            self.onGetWeekAttendanceClicked)
        self.getWeekAttendancePrimaryButton = PrimaryPushButton(
            self.tr("获取本周考勤"), parent=self)
        self.getWeekAttendancePrimaryButton.clicked.connect(
            self.onGetWeekAttendanceClicked)

        # 作为菜单触发器的按钮
        self.moreButton = TransparentPushButton("更多...", parent=self)
        self.moreButton.setFixedWidth(100)
        self.moreButton.clicked.connect(lambda: self.createMoreMenu(
            self.moreButton.mapToGlobal(QPoint(0, self.moreButton.height()))))

        self.lastWeekButton = PushButton('<', parent=self)
        self.lastWeekButton.setFixedWidth(45)
        self.weekComboBox = ComboBox(self)
        self.weekComboBox.addItems([str(i) for i in range(1, self.getWeekLength() + 1)])
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
        # 获得考试时间菜单项
        self.getExamAction = Action(FIF.BOOK_SHELF, self.tr("获取考试信息"))
        self.moreMenu.addAction(self.getExamAction)
        self.getExamAction.triggered.connect(self.onGetExamClicked)
        # 修改学期菜单项
        self.changeTermAction = Action(FIF.EDIT, self.tr("修改学期..."))
        self.moreMenu.addAction(self.changeTermAction)
        self.changeTermAction.triggered.connect(self.onChangeTermClicked)
        # 导出为 ics 菜单项
        self.exportAction = Action(FIF.SHARE, self.tr("导出 ics..."))
        self.moreMenu.addAction(self.exportAction)
        self.exportAction.triggered.connect(self.onExportClicked)
        # 修改开始日期菜单项
        self.changeTermStartAction = Action(FIF.DATE_TIME, self.tr("修改学期开始日期..."))
        self.moreMenu.addAction(self.changeTermStartAction)
        self.changeTermStartAction.triggered.connect(self.onChangeTermStartClicked)
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
        self.table_widget.setVerticalHeaderLabels([
            self.tr("一"),
            self.tr("二"),
            self.tr("三"),
            self.tr("四"),
            self.tr("午休"),
            self.tr("五"),
            self.tr("六"),
            self.tr("七"),
            self.tr("八"),
            self.tr("晚休"),
            self.tr("九"),
            self.tr("十"),
            self.tr("十一")
        ])
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
        self.table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.table_widget.horizontalHeader().setMinimumSectionSize(50)

        # 去除悬浮时高亮一行的效果，否则和合并的单元格放在一起很难看
        self.table_widget.entered.disconnect()
        self.table_widget.leaveEvent = lambda _: None

        self.table_widget.cellClicked.connect(self.onCellClicked)

        self.detailDialog = None

        self.vBoxLayout.addWidget(self.commandFrame)
        self.vBoxLayout.addWidget(self.process_widget_ehall)
        self.vBoxLayout.addWidget(self.process_widget_attendance)
        self.vBoxLayout.addWidget(self.process_widget_exam)
        self.vBoxLayout.addWidget(self.process_widget_graduate_schedule)
        self.vBoxLayout.addWidget(self.table_widget)

        # 加载可能存在的课表缓存到页面中
        if accounts.current is not None:
            if self.schedule_service.getStartOfTerm() is not None:
                self.loadSchedule()
                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
                # 设置考试查询学期
                self.schedule_exam_thread.term_number = self.schedule_service.getCurrentTerm()
            else:
                # 本学期没有课表，则不能设置学期开始时间（防止误判）
                self.getExamAction.setEnabled(False)
                self.changeTermStartAction.setEnabled(False)
                term = self.schedule_service.getCurrentTerm()
                if term is not None:
                    self.termButton.setText(
                        self.schedule_service.getCurrentTerm())
                    self.schedule_exam_thread.term_number = term

                self.setTablePrimary(True)
                self.setAttendancePrimary(False)
            # 研究生无法查询考试时间
            if accounts.current.type == accounts.current.POSTGRADUATE:
                self.getExamAction.setEnabled(False)
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

    def getWeekLength(self):
        """
        获得每个学期的周数长度。目前设置一般学期（编号 2020-2021-1/2020-2021-2）长度为 22 周，小学期（2020-2021-3）长度为 8 周
        """
        # 默认 22 周
        if self.schedule_service is None:
            return 22
        term = self.schedule_service.getCurrentTerm()
        if term is None:
            return 22
        # 在学期编号为 3 结尾的情况下（小学期），长度为 8 周
        if term.endswith("-3"):
            return 8
        return 22

    def getCurrentWeek(self):
        """
        获取当前周数，如果学期开始时间为空或大于当前日期，或者当前日期超过了学期结束时间，则返回 1。结果不会超过 22 周
        :return: 周数
        """
        start = self.schedule_service.getStartOfTerm()
        current = datetime.date.today()
        if start is None or start > current or (current -
                                                start).days // 7 >= self.getWeekLength():
            return 1
        return min((current - start).days // 7 + 1, self.getWeekLength())

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
        if current < self.getWeekLength() + 1:
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

    @pyqtSlot(Exam)
    def onExamDetailClicked(self, exam):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return
        start = self.schedule_service.getStartOfTerm()
        if start is None:
            self.error("", self.tr("请先获取课表"), parent=self)
            return
        # 更新最新的信息
        exam = Exam.get_by_id(exam.id)
        self.detailDialog = LessonDetailDialog(exam, start, self, self)
        self.detailDialog.rejected.connect(self.onCourseInfoFinished)
        self.detailDialog.exec()

    @pyqtSlot(int, int)
    def onCellClicked(self, row, column):
        if self.schedule_service is None:
            return

        cell_widget = self.table_widget.cellWidget(row, column)
        # 忽略午休和晚休的点击
        if row == 4 or row == 9 or row == 12:
            return
        if cell_widget is not None:
            return
        else:
            if row < 4:
                # 如果 0 行被点击，需要查看第一节课；1行被点击（第二节课的位置），仍然要查看第一节课。
                if row % 2 == 0:
                    start_time = row + 1
                else:
                    start_time = row
            elif row < 9:
                if row % 2 == 1:
                    start_time = row
                else:
                    start_time = row - 1
            else:
                # 晚上课程的点击写死为第九节课
                start_time = 9
            start_date = self.schedule_service.getStartOfTerm()
            self.detailDialog = LessonDetailDialog(self.week, column + 1,
                                                   start_time, start_time + 1,
                                                   start_date, self, self)
            self.detailDialog.rejected.connect(self.onCourseInfoFinished)
            self.detailDialog.exec()

    @pyqtSlot()
    def onCourseInfoFinished(self):
        if self.detailDialog.modified:
            # 这个写法虽然很奇怪，但是直接调用 loadSchedule 会导致课程表大小变得很小，不知道为什么
            # 这样做就没有问题
            if self.weekComboBox.currentIndex() != self.getWeekLength() - 1:
                self.weekComboBox.setCurrentIndex(
                    self.weekComboBox.currentIndex() + 1)
                self.weekComboBox.setCurrentIndex(
                    self.weekComboBox.currentIndex() - 1)
            else:
                # 最后一周时无法设置周数为下一周，所以先减再加
                self.weekComboBox.setCurrentIndex(
                    self.weekComboBox.currentIndex() - 1)
                self.weekComboBox.setCurrentIndex(
                    self.weekComboBox.currentIndex() + 1)

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

        self.getExamAction.setEnabled(False)
        self.changeTermAction.setEnabled(False)
        self.exportAction.setEnabled(False)
        self.clearAction.setEnabled(False)

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
        if self.week < self.getWeekLength():
            self.nextWeekButton.setEnabled(True)
        self.weekComboBox.setEnabled(True)
        self.process_widget_attendance.setVisible(False)
        self.process_widget_ehall.setVisible(False)

        self.getExamAction.setEnabled(True)
        self.changeTermAction.setEnabled(True)
        self.exportAction.setEnabled(True)
        self.clearAction.setEnabled(True)

    def success(self,
                title,
                msg,
                duration=2000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=None):
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
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title,
                                               msg,
                                               duration=duration,
                                               position=position,
                                               parent=parent)
        else:
            self._onlyNotice = InfoBar.success(
                title,
                msg,
                duration=-1,
                position=InfoBarPosition.TOP_RIGHT,
                parent=parent,
                isClosable=True)

    def error(self,
              title,
              msg,
              duration=2000,
              position=InfoBarPosition.TOP_RIGHT,
              parent=None):
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
            self._onlyNotice = InfoBar.error(title,
                                             msg,
                                             duration=duration,
                                             position=position,
                                             parent=parent)
        else:
            self._onlyNotice = InfoBar.error(
                title,
                msg,
                duration=-1,
                position=InfoBarPosition.TOP_RIGHT,
                parent=parent,
                isClosable=True)

    def warning(self,
                title,
                msg,
                duration=2000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=None):
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
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.warning(title,
                                               msg,
                                               duration=duration,
                                               position=position,
                                               parent=parent)
        else:
            self._onlyNotice = InfoBar.warning(
                title,
                msg,
                duration=-1,
                position=InfoBarPosition.TOP_RIGHT,
                parent=parent,
                isClosable=True)

    @pyqtSlot(str)
    def onThreadSuccess(self, msg):
        self.success(self.tr("成功"),
                     msg,
                     duration=2000,
                     position=InfoBarPosition.TOP_RIGHT,
                     parent=self)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title,
                   msg,
                   duration=3000,
                   position=InfoBarPosition.TOP_RIGHT,
                   parent=self)

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
        if week == self.getWeekLength():
            self.nextWeekButton.setEnabled(False)
        else:
            self.nextWeekButton.setEnabled(True)

        # 重置表头
        self.table_widget.setHorizontalHeaderLabels(self.DAYS)

        # 显示日期和本天特殊颜色
        start_date = self.schedule_service.getStartOfTerm()
        if start_date is not None:
            self.table_widget.setHorizontalHeaderLabels([
                (start_date +
                 datetime.timedelta(days=(week - 1) * 7 + i)).strftime("%m.%d")
                + "\t" + self.DAYS[i] for i in range(7)
            ])
            today = datetime.date.today()
            if start_date + datetime.timedelta(days=(
                    week - 1) * 7) <= today < start_date + datetime.timedelta(
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

        self.table_widget.clearSpans()
        for course in schedule:
            widget = ScheduleTableWidget(course)
            widget.clicked.connect(self.onLessonDetailClicked)
            # 如果课程的开始时间在第四节课前，说明是上午，放到 start_time - 1 行
            if course.start_time <= 4:
                self.table_widget.setCellWidget(course.start_time - 1,
                                                course.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    course.start_time - 1, course.day_of_week - 1,
                    course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第五节课后，说明是下午，放到 start_time 行（因为有一行午休是不用的）
            elif course.start_time <= 8:
                self.table_widget.setCellWidget(course.start_time,
                                                course.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    course.start_time, course.day_of_week - 1,
                    course.end_time - course.start_time + 1, 1)
            # 如果课程的开始时间在第九节课后，说明是晚上，放到 start_time + 1 行（因为有一行午休+一行晚休共计两行是不用的）
            else:
                self.table_widget.setCellWidget(course.start_time + 1,
                                                course.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    course.start_time + 1, course.day_of_week - 1,
                    course.end_time - course.start_time + 1, 1)

        exams = self.schedule_service.getExamInWeek(week)

        for exam in exams:
            widget = ScheduleTableWidget(exam)
            widget.clicked.connect(self.onExamDetailClicked)
            # 如果课程的开始时间在第四节课前，说明是上午，放到 start_time - 1 行
            if exam.start_time <= 4:
                self.table_widget.setCellWidget(exam.start_time - 1,
                                                exam.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    exam.start_time - 1, exam.day_of_week - 1,
                    exam.end_time - exam.start_time + 1, 1)
            # 如果课程的开始时间在第五节课后，说明是下午，放到 start_time 行（因为有一行午休是不用的）
            elif exam.start_time <= 8:
                self.table_widget.setCellWidget(exam.start_time,
                                                exam.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    exam.start_time, exam.day_of_week - 1,
                    exam.end_time - exam.start_time + 1, 1)
            # 如果课程的开始时间在第九节课后，说明是晚上，放到 start_time + 1 行（因为有一行午休+一行晚休共计两行是不用的）
            else:
                self.table_widget.setCellWidget(exam.start_time + 1,
                                                exam.day_of_week - 1, widget)
                self.table_widget.setSpan(
                    exam.start_time + 1, exam.day_of_week - 1,
                    exam.end_time - exam.start_time + 1, 1)

        if schedule or exams:
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
        self.graduate_schedule_thread.term_number = term_number
        if not self.schedule_service.getCourseInTerm(term_number):
            self.lock()
            if accounts.current.type == accounts.current.UNDERGRADUATE:
                self.process_widget_ehall.setVisible(True)
                self.schedule_thread.start()
            else:
                self.process_widget_graduate_schedule.setVisible(True)
                self.graduate_schedule_thread.start()
        else:
            w = MessageBox(self.tr("获取课表"),
                           self.tr("获取课表后，所有非手动添加的课程及其考勤状态将会清空，是否继续？"), self)
            w.yesButton.setText(self.tr("确定"))
            w.cancelButton.setText(self.tr("取消"))
            if w.exec():
                self.lock()
                if accounts.current.type == accounts.current.UNDERGRADUATE:
                    self.process_widget_ehall.setVisible(True)
                    self.schedule_thread.start()
                else:
                    self.process_widget_graduate_schedule.setVisible(True)
                    self.graduate_schedule_thread.start()

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

        self.schedule_attendance_thread.start_date = start_date
        self.schedule_attendance_thread.end_date = end_date
        setting = cfg.get(cfg.defaultAttendanceLoginMethod)
        if setting == cfg.AttendanceLoginMethod.WEBVPN:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
        elif setting == cfg.AttendanceLoginMethod.NORMAL:
            self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
        else:
            if not self.schedule_attendance_thread.session.has_login:
                w = MessageBox(self.tr("获取考勤"), self.tr("您想使用什么方式登录考勤系统？"),
                               self)
                w.yesButton.setText(self.tr("WebVPN 登录"))
                w.cancelButton.setText(self.tr("直接登录"))
                if w.exec():
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
                else:
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
            else:
                if self.schedule_attendance_thread.session.login_method == AttendanceSession.LoginMethod.NORMAL:
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.NORMAL_LOGIN
                else:
                    self.schedule_attendance_thread.login_method = AttendanceFlowLogin.WEBVPN_LOGIN
        self.lock()
        self.process_widget_attendance.setVisible(True)
        self.schedule_attendance_thread.start()
        self.schedule_attendance_monitor_thread.start()

    @pyqtSlot()
    def onGetExamClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return
        if not self.schedule_service.getCurrentTerm():
            self.error(self.tr("未获取课表"), self.tr("请先获取课表"), parent=self)
            return

        self.process_widget_exam.setVisible(True)
        self.lock()
        self.schedule_exam_thread.start()

    @pyqtSlot()
    def onChangeTermClicked(self):
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        w = ChangeTermDialog(self)
        if w.exec():
            self.schedule_service.setCurrentTerm(w.term_number)
            self.schedule_exam_thread.term_number = w.term_number

            # 未获取过课表时，无法查询考试时间和修改学期开始日期
            if self.schedule_service.getStartOfTerm() is not None:
                self.getExamAction.setEnabled(True)
                self.changeTermStartAction.setEnabled(True)
            else:
                self.getExamAction.setEnabled(True)
                self.changeTermStartAction.setEnabled(False)

            # 重新根据学期长度设置下拉框
            self.weekComboBox.clear()
            self.weekComboBox.addItems([str(i) for i in range(1, self.getWeekLength() + 1)])
            self.loadSchedule()

    @pyqtSlot()
    def onChangeTermStartClicked(self):
        """
        修改当前学期的开始日期
        """
        if self.schedule_service is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            return

        date = self.schedule_service.getStartOfTerm()
        if date is None:
            date = self.guessTermStartDate(self.schedule_service.getCurrentTerm())
            print(date)
        w = TermStartTimeDialog(date, self)
        if w.exec():
            self.schedule_service.setTermInfo(self.schedule_service.getCurrentTerm(), w.date.isoformat())
            self.loadSchedule()

    @staticmethod
    def guessTermStartDate(term_number):
        """
        根据一个学期编号，猜测一个学期开始日期（用于给修改学期开始日期对话框填充初始数据）
        :param term_number: 学期编号，比如 2020-2021-1
        """
        def get_nearest_monday(date: datetime.date):
            """
            获得距离某个日期前后最近的星期一
            """
            last_monday = date
            last_delta = 0
            while last_monday.weekday() != 0:
                last_monday -= datetime.timedelta(days=1)
                last_delta += 1
            next_monday = date
            next_delta = 0
            while next_monday.weekday() != 0:
                next_monday += datetime.timedelta(days=1)
                next_delta += 1
            return last_monday if last_delta <= next_delta else next_monday

        start_year, end_year, semester = term_number.split("-")
        start_year = int(start_year)
        end_year = int(end_year)
        semester = int(semester)
        if semester == 1:
            # 第一个学期，设定为 9 月第一个周一
            date = datetime.date(start_year, 9, 1)
            # 一直+1直到日期是周一
            while date.weekday() != 0:
                date += datetime.timedelta(days=1)
            return date
        elif semester == 2:
            # 第二个学期，选择二月最后一个周一或者三月第一个周一（根据二者哪个距离 3 月 1 日最近）
            date = datetime.date(end_year, 3, 1)
            return get_nearest_monday(date)
        elif semester == 3:
            # 夏季小学期，找 7 月的第一个星期一或者 6 月最后一个周一（根据二者哪个距离 7 月 1 日最近）
            date = datetime.date(year=end_year, month=7, day=1)
            return get_nearest_monday(date)
        else:
            # 默认值 1 月 1 日
            return datetime.date(year=start_year, month=1, day=1)

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
            if os.path.exists(os.path.dirname(
                    w.result_path)) and not os.path.isdir(w.result_path):
                self.exportICS(w.result_path, w.ignore_holiday, w.set_alarm)
            else:
                self.error("", self.tr("导出位置不存在"), parent=self)

    def exportICS(self, path, ignore_holiday=True, set_alarm=True):
        """
        导出课程表为 ics 文件
        :param path: 导出路径
        :param ignore_holiday: 是否忽略节假日
        :param set_alarm: 是否在课程和考试事件中设置提醒
        """
        self._export_path = path
        if ignore_holiday:
            ignore_data = cacheManager.read_expire_json(
                "ignore_holiday.json", 7)
            if ignore_data is not None:
                for i in range(len(ignore_data)):
                    ignore_data[i] = datetime.datetime.strptime(
                        ignore_data[i], "%Y-%m-%d").date()
            else:
                self.stateToolTip = StateToolTip(self.tr("正在获取节假日信息..."),
                                                 self.tr("请稍等..."), self)
                self.stateToolTip.move(self.stateToolTip.getSuitablePos())
                self.stateToolTip.show()
                self.holiday_thread.start()
                return

        else:
            ignore_data = []

        self.export(path, ignore_data, set_alarm)

    @pyqtSlot(str, str)
    def onHolidayError(self, title, msg):
        if self.stateToolTip is not None:
            self.stateToolTip.setState(False)
            self.stateToolTip.setContent(msg)
            self.stateToolTip = None

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

    def export(self, path, ignore_holidays: list[datetime.date], set_alarm: bool = True):
        """
        内部函数，实际实现导出功能
        :param path: 导出目标的路径
        :param ignore_holidays: 需要忽略的节假日日期
        :param set_alarm: 是否在课程和考试事件中设置提醒
        :return:
        """
        LOCAL_TIMEZONE = pytz.timezone("Asia/Shanghai")  # 设定为北京时间
        term_start = self.schedule_service.getStartOfTerm()
        if term_start is None:
            raise ValueError("学期开始时间为空")

        cal = Calendar()

        for course in self.schedule_service.getCourseInTerm():

            term_start_time = datetime.datetime(term_start.year,
                                                term_start.month,
                                                term_start.day)
            date = term_start_time + datetime.timedelta(
                days=(course.week_number - 1) * 7 + course.day_of_week - 1)

            e = Event()
            name = course.name if course.name else ""
            location = course.location if course.location else ""
            e.add("summary", name)
            e.add("description", f"{name} {location}")
            # 有的课程可能没有地点信息，如果没有就不添加这个字段
            if location:
                e.add('location', location)

            if date.date() in ignore_holidays:
                continue

            begin_time = getClassStartTime(course.start_time,
                                           isSummerTime(date))
            end_time = getClassEndTime(course.end_time, isSummerTime(date))

            e.add(
                "dtstart",
                LOCAL_TIMEZONE.localize(
                    date.replace(hour=begin_time.hour,
                                 minute=begin_time.minute)))
            e.add(
                "dtend",
                LOCAL_TIMEZONE.localize(
                    date.replace(hour=end_time.hour,
                                 minute=end_time.minute)))

            if set_alarm:
                alarm = Alarm()
                alarm.add("action", "display")
                alarm.add("description", self.tr("上课提醒"))
                alarm.add("trigger", datetime.timedelta(minutes=-15))
                e.add_component(alarm)

            cal.add_component(e)

        for exam in self.schedule_service.getExamInTerm():
            term_start_time = datetime.datetime(term_start.year,
                                                term_start.month,
                                                term_start.day)
            date = term_start_time + datetime.timedelta(
                days=(exam.week_number - 1) * 7 + exam.day_of_week - 1)

            e = Event()
            e.add("summary", exam.name)
            e.add("description", self.tr("座位号:") + exam.seat_number)
            e.add('location', exam.location)

            begin_time = exam.start_exact_time
            end_time = exam.end_exact_time

            e.add(
                "dtstart",
                LOCAL_TIMEZONE.localize(
                    date.replace(hour=begin_time.hour,
                                 minute=begin_time.minute)))
            e.add(
                "dtend",
                LOCAL_TIMEZONE.localize(
                    date.replace(hour=end_time.hour,
                                 minute=end_time.minute)))

            if set_alarm:
                alarm = Alarm()
                alarm.add("action", "display")
                alarm.add("description", self.tr("考试提醒"))
                alarm.add("trigger", datetime.timedelta(minutes=-30))
                e.add_component(alarm)

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
        if schedule["start_date"] is None:
            # 研究生没有获取到学期开始时间，则允许手动设置一下
            w = TermStartTimeDialog(self.guessTermStartDate(schedule["term_number"]), self)
            if w.exec():
                schedule["start_date"] = w.date.isoformat()
            else:
                w = MessageBox(self.tr("获取课表失败"),
                               self.tr("由于无法获得此学期的开始时间，因此未能添加课表"), parent=self)
                w.yesButton.setText(self.tr("确认"))
                w.cancelButton.hide()
                w.exec()
                return

        self.schedule_service.setTermInfo(schedule["term_number"],
                                          schedule["start_date"], True)
        self.schedule_service.clearNonManualCourses()

        conflicts = []
        new_courses = []
        if self.sender() == self.schedule_thread:
            for lesson in schedule["lessons"]:
                new_courses.append(
                    self.schedule_service.getCourseGroupFromJson(lesson,
                                                                 manual=False))
        else:
            for lesson in schedule["lessons"]:
                new_courses.append(
                    self.schedule_service.getGraduateCourseGroupFromJson(
                        lesson, schedule["term_number"], manual=False))

        for one_course in new_courses:
            old_course = self.schedule_service.getCourseGroupInCertainTime(
                one_course.day_of_week, one_course.start_time,
                one_course.end_time, one_course.term_number)
            if old_course:
                old_course = list(old_course)[0]
                if isinstance(old_course.week_numbers, int):
                    old_course.week_numbers = [old_course.week_numbers]
                else:
                    old_course.week_numbers = old_course.week_numbers.split(
                        ",")
                    old_course.week_numbers = [
                        int(i) for i in old_course.week_numbers
                    ]

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
                        self.schedule_service.deleteCourseFromGroup(
                            conflicts[index][1])
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
                    self.schedule_service.addCourseFromGroup(
                        course, merge_with_existing=True)

                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
                self.loadSchedule()
            else:
                # 取消合并，那么就不添加新获取的课程了
                # 刷新一下页面
                self.loadSchedule()
                return

        else:
            # 根据查询者是本科生还是研究生（给出信息的线程是哪个），使用不同接口添加课程。
            if self.sender() == self.schedule_thread:
                for lesson in schedule["lessons"]:
                    self.schedule_service.addCourseFromJson(
                        lesson, merge_with_existing=True, manual=False)
            else:
                for lesson in schedule["lessons"]:
                    self.schedule_service.addGraduateCourseFromJson(
                        lesson, schedule["term_number"],
                        merge_with_existing=True, manual=False)

        self.setTablePrimary(False)
        self.setAttendancePrimary(True)
        self.loadSchedule()

    @pyqtSlot(dict)
    def onReceiveExam(self, exam: dict):
        self.schedule_service.addExamFromJson(exam)
        self.loadSchedule()

    @pyqtSlot(list, list)
    def onReceiveAttendance(self, records: list[AttendanceWaterRecord],
                            water_page: list[AttendanceFlow]):
        updated = []
        for record in records:
            try:
                lesson = self.schedule_service.selectCourse(
                    CourseInstance.week_number == record.week,
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
                water_time = datetime.datetime.strptime(
                    page.water_time, "%Y-%m-%d %H:%M:%S")
                date = water_time.date()
                week = (water_time.date() -
                        self.schedule_service.getStartOfTerm()).days // 7 + 1
                lessons = self.schedule_service.selectCourse(
                    CourseInstance.week_number == week,
                    CourseInstance.day_of_week == date.weekday() + 1,
                    CourseInstance.location == page.place)
                for lesson in lessons:
                    # 如果这门课程已经查询到了考勤状态，就不更新打卡状态
                    if lesson.status != CourseStatus.UNKNOWN.value:
                        continue
                    # 比较打卡流水时间是否在考勤时间内
                    if getAttendanceStartTime(
                            lesson.start_time, isSummerTime(date)
                    ) <= water_time.time() <= getAttendanceEndTime(
                            lesson.start_time, isSummerTime(date)):
                        lesson.status = CourseStatus.CHECKED.value
                        lesson.save()
                        updated.append(lesson)

        for i in range(7):
            for j in range(13):
                widget: ScheduleTableWidget = self.table_widget.cellWidget(
                    j, i)
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
                os.path.join(account_data_directory(accounts.current),
                             "schedule.db"))
            if self.schedule_service.getStartOfTerm() is not None:
                self.setTablePrimary(False)
                self.setAttendancePrimary(True)
            else:
                self.setTablePrimary(True)
                self.setAttendancePrimary(False)
            self.loadSchedule()
            # 如果当前账户是研究生，禁用考试时间查询按键（因为研究生系统没有对应的 API）
            if accounts.current.type == accounts.current.POSTGRADUATE:
                self.getExamAction.setEnabled(False)
            else:
                self.getExamAction.setEnabled(True)
