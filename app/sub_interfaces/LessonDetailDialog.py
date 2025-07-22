import datetime
from datetime import date, timedelta
from typing import Optional

from PyQt5.QtCore import pyqtProperty, Qt, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QVBoxLayout, QWidget, QLabel, QHBoxLayout, QTableWidgetItem, QHeaderView, QFrame
from qfluentwidgets import MessageBoxBase, SimpleCardWidget, setFont, FluentStyleSheet, \
    FluentIcon, TransparentPushButton, TableWidget, ScrollArea, FlyoutViewBase, FlowLayout, \
    CheckBox, Flyout, LineEdit, PrimaryPushButton, PushButton, BodyLabel
from qfluentwidgets.common.overload import singledispatchmethod
from qfluentwidgets.components.widgets.card_widget import CardSeparator

from app.utils import accounts
from schedule import getClassStartTime, getClassEndTime
from schedule.schedule_database import CourseInstance, CourseStatus, Exam
from schedule.schedule_service import ScheduleService
from schedule.xjtu_time import isSummerTime


class WeekFlyoutView(FlyoutViewBase):
    def __init__(self, weeks, select_week=None, lock_weeks=None, week_numbers=22, parent=None):
        """
        创建一个用于选择周数的浮窗
        :param weeks: 所有初始选择的周数
        :param select_week: 要强制某周为选择状态，传入该周的数字
        :param lock_weeks: 要锁定（不允许选择）的周数，传入一个列表
        :param week_numbers: 总周数，默认为 22 周
        :param parent: 父对象
        """
        super().__init__(parent)
        self.weeks = set(weeks)
        self.weeksLayout = FlowLayout(self)
        self.weeksLayout.setSpacing(8)
        self.checkbox = []
        self.setMinimumWidth(300)

        for week in range(1, week_numbers + 1):
            checkbox = CheckBox(f"第{week}周", self)
            checkbox.setMinimumWidth(150)
            checkbox.setChecked(week in self.weeks)
            checkbox.stateChanged.connect(self.onWeekChanged)
            self.weeksLayout.addWidget(checkbox)
            self.checkbox.append(checkbox)
        if select_week is not None:
            self.checkbox[select_week - 1].setChecked(True)
            self.checkbox[select_week - 1].setEnabled(False)
        if lock_weeks is not None:
            for week in lock_weeks:
                self.checkbox[week - 1].setEnabled(False)
                self.checkbox[week - 1].setToolTip(self.tr("此周已有课程，无法修改"))

    def onWeekChanged(self, _):
        for i, checkbox in enumerate(self.checkbox):
            if checkbox.isChecked():
                self.weeks.add(i + 1)
            else:
                self.weeks.discard(i + 1)


class ConfirmFlyoutView(FlyoutViewBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.button_layout = QHBoxLayout(self)
        self.confirm_all_button = PrimaryPushButton(self.tr("修改所有周信息"), self)
        self.confirm_one_button = PushButton(self.tr("仅修改本周信息"), self)
        self.button_layout.addWidget(self.confirm_all_button)
        self.button_layout.addWidget(self.confirm_one_button)


class DeleteFlyoutView(FlyoutViewBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.button_layout = QHBoxLayout(self)
        self.confirm_all_button = PrimaryPushButton(self.tr("删除所有周"), self)
        self.confirm_one_button = PushButton(self.tr("仅删除本周"), self)
        self.button_layout.addWidget(self.confirm_all_button)
        self.button_layout.addWidget(self.confirm_one_button)


class DeleteAllFlyoutView(FlyoutViewBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.button_layout = QHBoxLayout(self)
        self.confirm_button = PrimaryPushButton(self.tr("确认删除"), self)
        self.cancel_button = PushButton(self.tr("取消"), self)
        self.button_layout.addWidget(self.confirm_button)
        self.button_layout.addWidget(self.cancel_button)


class HeaderCardWidget(SimpleCardWidget):
    """为了让这个 widget 的内部布局改成 QVBoxLayout 而不是默认的 QHBoxLayout，我不得不复制粘贴整个类的代码，然后修改其中的一点代码。"""

    @singledispatchmethod
    def __init__(self, parent=None):
        super().__init__(parent)
        self.headerView = QWidget(self)
        self.headerLabel = QLabel(self)
        self.headerEdit = LineEdit(self)
        self.separator = CardSeparator(self)
        self.view = QWidget(self)

        self.vBoxLayout = QVBoxLayout(self)
        self.headerLayout = QHBoxLayout(self.headerView)
        self.viewLayout = QVBoxLayout(self.view)

        self.headerLayout.addWidget(self.headerLabel)
        self.headerLayout.addWidget(self.headerEdit)
        self.headerEdit.setVisible(False)
        self.headerLayout.setContentsMargins(24, 0, 16, 0)
        self.headerView.setFixedHeight(48)

        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.headerView)
        self.vBoxLayout.addWidget(self.separator)
        self.vBoxLayout.addWidget(self.view)

        setFont(self.headerLabel, 15, QFont.DemiBold)

        self.view.setObjectName('view')
        self.headerView.setObjectName('headerView')
        self.headerLabel.setObjectName('headerLabel')
        FluentStyleSheet.CARD_WIDGET.apply(self)

    def startEdit(self):
        self.headerLabel.setVisible(False)
        self.headerEdit.setVisible(True)
        self.headerEdit.setText(self.headerLabel.text())

    def confirmEdit(self):
        self.headerLabel.setVisible(True)
        self.headerEdit.setVisible(False)
        self.headerLabel.setText(self.headerEdit.text())

    def cancelEdit(self):
        self.headerLabel.setVisible(True)
        self.headerEdit.setVisible(False)
        self.headerEdit.setText(self.headerLabel.text())

    @__init__.register
    def _(self, title: str, parent=None):
        self.__init__(parent)
        self.setTitle(title)

    def getTitle(self):
        return self.headerLabel.text()

    def setTitle(self, title: str):
        self.headerLabel.setText(title)

    title = pyqtProperty(str, getTitle, setTitle)


class LessonCard(HeaderCardWidget):
    # 此卡片对应的课程被删除时，会发送的信息
    courseDeleted = pyqtSignal(CourseInstance)

    def __init__(self, course: CourseInstance, start_time: date, service: ScheduleService, ambiguous_time=False,
                 delete_all=False,
                 on_edit_trigger=None, parent=None):
        """
        创建一个用于展示课程的卡片
        :param course: 课程对象
        :param start_time: 学期开始时间。如果设置 ambiguous_time 为 True，则直接传入 None 即可。
        :param service: schedule_service 的对象
        :param ambiguous_time: 是否使用模糊时间。如果是，则只显示课程开始-结束节次，不显示具体时间。
        如果需要显示具体时间（False），那么 course 的 week 属性不能为 None。
        :param delete_all: 在删除时，是否默认删除所有周的课程。对于通过「展开」按钮创建的卡片，此选项应当设置为 True，因为此时删除当前周不会起效
        :param on_edit_trigger: 当课程被编辑时的回调函数
        :param parent: 父对象
        """
        super().__init__(parent)
        self.status_dict = {
            CourseStatus.UNKNOWN: self.tr("未知"),
            CourseStatus.CHECKED: self.tr("已打卡"),
            CourseStatus.NORMAL: self.tr("正常"),
            CourseStatus.LEAVE: self.tr("请假"),
            CourseStatus.LATE: self.tr("迟到"),
            CourseStatus.ABSENT: self.tr("缺勤"),
            CourseStatus.NO_CHECK: self.tr("无需考勤")
        }

        self.course = course
        self.editable = False
        self.start_time = start_time
        self.setTitle(course.name)
        self.ambiguous_time = ambiguous_time

        self.on_edit_trigger = on_edit_trigger

        self.schedule_service = service

        self.weeks_flyout = None
        self.weeks = self.getAllWeeks()
        self.confirm_flyout = None
        self.delete_flyout = None
        self.delete_all = delete_all

        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setRowCount(5)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setWordWrap(True)

        self.viewLayout.addWidget(self.table)

        self.functionFrame = QFrame(self)
        self.functionFrame.setContentsMargins(0, 0, 0, 0)
        self.functionLayout = QHBoxLayout(self.functionFrame)
        self.editButton = TransparentPushButton(FluentIcon.EDIT, self.tr("编辑"), self)
        self.functionLayout.addWidget(self.editButton)
        self.deleteButton = TransparentPushButton(FluentIcon.DELETE, self.tr("删除"), self)
        self.functionLayout.addWidget(self.deleteButton)
        self.editButton.clicked.connect(self.startEdit)
        self.deleteButton.clicked.connect(self.onDeleteClicked)

        self.viewLayout.addWidget(self.functionFrame)

        self.confirmFrame = QFrame(self)
        self.confirmFrame.setContentsMargins(0, 0, 0, 0)
        self.confirmLayout = QHBoxLayout(self.confirmFrame)
        self.confirmButton = TransparentPushButton(FluentIcon.ACCEPT, self.tr("确定"), self)
        self.confirmButton.clicked.connect(self.checkEdit)
        self.confirmLayout.addWidget(self.confirmButton)

        self.cancelButton = TransparentPushButton(FluentIcon.CLOSE, self.tr("取消"), self)
        self.cancelButton.clicked.connect(self.cancelEdit)
        self.confirmLayout.addWidget(self.cancelButton)

        self.viewLayout.addWidget(self.confirmFrame)

        self.other_courses = None
        self.other_weeks = None

        self.loadDataFromCourse()
        self.table.cellClicked.connect(self.onTableWidgetClicked)

        self.confirmFrame.setVisible(False)
        self.table.setMinimumWidth(400)
        if ambiguous_time:
            self.table.setMinimumHeight(150)
        else:
            self.table.setMinimumHeight(192)

        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def getAllWeeks(self):
        weeks = [course.week_number for course in self.schedule_service.getSameCourseInOtherWeek(self.course)]
        weeks.sort()
        return weeks

    def loadDataFromCourse(self):
        """
        按照课程的信息，填充表格。此方法会重置当前课程被修改的信息。
        """
        self.weeks = self.getAllWeeks()
        weeks = [str(week) for week in self.weeks]
        if self.ambiguous_time:
            class_start_time = self.course.start_time
            class_end_time = self.course.end_time
        else:
            is_summer_time = isSummerTime(self.start_time + timedelta(days=(
                    (self.course.week_number - 1) * 7 + self.course.day_of_week -
                    1)))
            class_start_time = getClassStartTime(
                self.course.start_time, is_summer_time).strftime("%H:%M")
            class_end_time = getClassEndTime(self.course.end_time,
                                             is_summer_time).strftime("%H:%M")
        if self.ambiguous_time:
            self.table.setRowHidden(0, True)
        else:
            self.table.setItem(0, 0, QTableWidgetItem(self.tr("状态")))
            self.table.setItem(
                0, 1,
                QTableWidgetItem(
                    self.status_dict.get(CourseStatus(self.course.status),
                                         self.tr("未知"))))
        self.table.setItem(1, 0, QTableWidgetItem(self.tr("时间")))
        self.table.setItem(
            1, 1, QTableWidgetItem(f"{class_start_time} - {class_end_time}"))
        self.table.setItem(2, 0, QTableWidgetItem(self.tr("教师")))
        self.table.setItem(2, 1, QTableWidgetItem(self.course.teacher))
        self.table.setItem(3, 0, QTableWidgetItem(self.tr("地点")))
        self.table.setItem(3, 1, QTableWidgetItem(self.course.location))
        self.table.setItem(4, 0, QTableWidgetItem(self.tr("上课周")))
        self.table.setItem(4, 1, QTableWidgetItem(f"{','.join(weeks)}"))
        self.table.adjustSize()

    @pyqtSlot()
    def startEdit(self):
        super().startEdit()
        self.functionFrame.setVisible(False)
        self.confirmFrame.setVisible(True)

        self.editable = True
        self.table.setEditTriggers(TableWidget.AllEditTriggers)

        # 重新生成其他周课程
        self.other_courses = self.schedule_service.getOtherCourseInSameTime(self.course)
        self.other_weeks = []
        for course in self.other_courses:
            if isinstance(course.week_numbers, int):
                self.other_weeks.append(course.week_numbers)
            else:
                for one in course.week_numbers.split(","):
                    self.other_weeks.append(int(one))

        if not self.table.isRowHidden(0):
            self.table.item(0, 0).setFlags(Qt.ItemIsEnabled)
            self.table.item(0, 1).setFlags(Qt.ItemIsEnabled)

        self.table.item(1, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(1, 1).setFlags(Qt.ItemIsEnabled)
        self.table.item(2, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(3, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(4, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(4, 1).setFlags(Qt.ItemIsEnabled)

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

    @pyqtSlot(int, int)
    def onTableWidgetClicked(self, row, col):
        if row == 4 and col == 1:
            if self.editable:
                self.weeks_flyout = Flyout.make(
                    target=self.table,
                    view=WeekFlyoutView(weeks=self.weeks, lock_weeks=self.other_weeks,
                                        select_week=self.course.week_number, week_numbers=self.getWeekLength()),
                    parent=self
                )
                self.weeks_flyout.closed.connect(self.onWeekFlyoutClosed)

    @pyqtSlot()
    def onWeekFlyoutClosed(self):
        self.weeks = list(self.weeks_flyout.view.weeks)
        self.weeks.sort()
        self.table.item(4, 1).setText(",".join(str(week) for week in self.weeks))

    @pyqtSlot()
    def checkEdit(self):
        """
        检查当前卡片在编辑状态下被编辑的内容，决定是否要弹出「询问修改单周课程还是全部课程」的浮窗
        """
        # 获得修改前的信息
        old_course_name = self.course.name
        old_teacher = self.course.teacher
        old_location = self.course.location
        old_weeks = self.getAllWeeks()
        # 获得修改后的信息
        new_course_name = self.headerEdit.text()
        new_teacher = self.table.item(2, 1).text()
        new_location = self.table.item(3, 1).text()
        new_weeks = self.weeks
        # 比较信息。如果仅有 weeks 信息被修改，不需要弹出确认信息；如果其他任何信息被修改，需要弹出确认信息
        if old_course_name == new_course_name and old_teacher == new_teacher and old_location == new_location:
            if old_weeks != new_weeks:
                self.confirmWeekEdit()
            else:
                self.cancelEdit()
        else:
            self.confirm_flyout = Flyout.make(
                target=self.confirmButton,
                view=ConfirmFlyoutView(),
                parent=self
            )
            self.confirm_flyout.view.confirm_all_button.clicked.connect(self.confirmAllWeekEdit)
            self.confirm_flyout.view.confirm_one_button.clicked.connect(self.confirmOneWeekEdit)

    @pyqtSlot()
    def confirmWeekEdit(self):
        """
        修改课程上课的周数，增加/删除课程
        """
        if self.on_edit_trigger is not None:
            self.on_edit_trigger()
        old_weeks = self.getAllWeeks()
        new_weeks = self.weeks
        # 删除不需要的课程
        deleted = [week for week in old_weeks if week not in new_weeks]
        # 添加新的课程
        added = [week for week in new_weeks if week not in old_weeks]
        # 删除课程
        self.schedule_service.deleteCourseInWeeks(self.course, deleted)
        # 添加课程
        self.schedule_service.addCourseInWeeks(self.course, added)
        self.finishEdit()

    @pyqtSlot()
    def confirmOneWeekEdit(self):
        """
        根据编辑后的内容修改课表，且仅修改当前周的课程
        """
        if self.on_edit_trigger is not None:
            self.on_edit_trigger()
        new_name = self.headerEdit.text()
        new_teacher = self.table.item(2, 1).text()
        new_location = self.table.item(3, 1).text()

        self.schedule_service.editSingleCourse(self.course, new_name, new_location, new_teacher)
        self.headerLabel.setText(new_name)
        self.confirmWeekEdit()
        self.confirm_flyout.close()

    @pyqtSlot()
    def confirmAllWeekEdit(self):
        """
        根据编辑后的内容修改课表，且修改当前时间段在所有周的课程
        """
        if self.on_edit_trigger is not None:
            self.on_edit_trigger()

        new_name = self.headerEdit.text()
        new_teacher = self.table.item(2, 1).text()
        new_location = self.table.item(3, 1).text()

        self.schedule_service.editMultiWeekCourse(self.course, new_name, new_location, new_teacher)
        self.headerLabel.setText(new_name)
        self.confirmWeekEdit()
        self.confirm_flyout.close()

    @pyqtSlot()
    def onDeleteClicked(self):
        if self.delete_all:
            self.delete_flyout = Flyout.make(
                target=self.deleteButton,
                view=DeleteAllFlyoutView(),
                parent=self
            )
            self.delete_flyout.view.confirm_button.clicked.connect(self.confirmAllWeekDelete)
            self.delete_flyout.view.cancel_button.clicked.connect(self.delete_flyout.close)
        else:
            self.delete_flyout = Flyout.make(
                target=self.deleteButton,
                view=DeleteFlyoutView(),
                parent=self
            )
            self.delete_flyout.view.confirm_all_button.clicked.connect(self.confirmAllWeekDelete)
            self.delete_flyout.view.confirm_one_button.clicked.connect(self.confirmOneWeekDelete)

    @pyqtSlot()
    def confirmOneWeekDelete(self):
        """
        删除当前周的课程
        """
        self.course.delete_instance(recursive=False)
        self.finishEdit()
        self.delete_flyout.close()
        self.courseDeleted.emit(self.course)

    @pyqtSlot()
    def confirmAllWeekDelete(self):
        """
        删除当前时间段在所有周的课程
        """
        self.schedule_service.deleteMultiWeekCourse(self.course)
        self.finishEdit()
        self.delete_flyout.close()
        self.courseDeleted.emit(self.course)

    def finishEdit(self):
        """
        结束编辑，但不重新加载内容
        """
        self.functionFrame.setVisible(True)
        self.confirmFrame.setVisible(False)

        self.editable = False
        self.headerEdit.setVisible(False)
        self.headerLabel.setVisible(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)

    @pyqtSlot()
    def cancelEdit(self):
        super().cancelEdit()
        self.functionFrame.setVisible(True)
        self.confirmFrame.setVisible(False)

        self.editable = False
        self.table.setEditTriggers(TableWidget.NoEditTriggers)

        self.loadDataFromCourse()


class EmptyLessonCard(HeaderCardWidget):
    """
    用于展示空白节次的课程卡片。
    """
    # 添加课程后，传递被添加课程在本周的对象
    # 由于 UI 设计，添加课程时一定会添加本周的周次
    courseAdded = pyqtSignal(CourseInstance)

    def __init__(self, week, day_of_week, start_time, end_time, service: ScheduleService, parent=None):
        """
        创建一个空白的课程卡片
        :param week: 此卡片表示的周数
        :param day_of_week: 此卡片表示的星期几
        :param start_time: 此卡片表示的课程开始时间
        :param end_time: 此卡片表示的课程结束时间
        :param service: schedule_service 的对象
        :param parent: 父对象
        """
        super().__init__(parent)
        # 一般的界面
        self.on_mouse_release = lambda ev: self.startEdit()
        self.hintLabel = BodyLabel(self.tr("点击以添加课程"), self)
        self.hintLabel.setMinimumWidth(400)
        self.hintLabel.setMinimumHeight(200)
        self.hintLabel.setAlignment(Qt.AlignCenter)
        self.hintLabel.mouseReleaseEvent = self.on_mouse_release
        self.viewLayout.addWidget(self.hintLabel)

        self.headerEdit.setPlaceholderText(self.tr("请输入课程名称"))
        self.current_week = week
        self.day_of_week = day_of_week
        self.start_time = start_time
        self.end_time = end_time

        # 添加课程的界面
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setRowCount(3)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.viewLayout.addWidget(self.table)
        self.weeks = [week]
        self.weeks_flyout = None

        self.schedule_service = service

        self.table.setItem(0, 0, QTableWidgetItem(self.tr("教师")))
        self.table.setItem(0, 1, QTableWidgetItem(""))
        self.table.setItem(1, 0, QTableWidgetItem(self.tr("地点")))
        self.table.setItem(1, 1, QTableWidgetItem(""))
        self.table.setItem(2, 0, QTableWidgetItem(self.tr("上课周")))
        self.table.setItem(2, 1, QTableWidgetItem(f"{week}"))
        self.table.adjustSize()

        self.confirmFrame = QFrame(self)
        self.confirmFrame.setContentsMargins(0, 0, 0, 0)
        self.confirmLayout = QHBoxLayout(self.confirmFrame)
        self.confirmButton = TransparentPushButton(FluentIcon.ACCEPT, self.tr("确定"), self)
        self.confirmButton.clicked.connect(self.checkEdit)
        self.confirmLayout.addWidget(self.confirmButton)

        self.cancelButton = TransparentPushButton(FluentIcon.CLOSE, self.tr("取消"), self)
        self.cancelButton.clicked.connect(self.cancelEdit)
        self.confirmLayout.addWidget(self.cancelButton)
        self.viewLayout.addWidget(self.confirmFrame)

        self.table.cellClicked.connect(self.onTableWidgetClicked)

        self.other_courses = None
        self.other_weeks = None

        self.confirmFrame.setVisible(False)
        self.table.setMinimumWidth(400)

        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.editable = False
        self.switchTo(False)

    def switchTo(self, editable: bool):
        self.editable = editable
        if editable:
            self.hintLabel.setVisible(False)
            self.table.setVisible(True)
            self.confirmFrame.setVisible(True)
        else:
            self.hintLabel.setVisible(True)
            self.table.setVisible(False)
            self.confirmFrame.setVisible(False)

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

    @pyqtSlot(int, int)
    def onTableWidgetClicked(self, row, col):
        if row == 2 and col == 1:
            if self.editable:
                self.weeks_flyout = Flyout.make(
                    target=self.table,
                    view=WeekFlyoutView(weeks=self.weeks, select_week=self.current_week, lock_weeks=self.other_weeks,
                                        week_numbers=self.getWeekLength()),
                    parent=self
                )
                self.weeks_flyout.closed.connect(self.onWeekFlyoutClosed)

    @pyqtSlot()
    def onWeekFlyoutClosed(self):
        self.weeks = list(self.weeks_flyout.view.weeks)
        self.weeks.sort()
        self.table.item(2, 1).setText(",".join(str(week) for week in self.weeks))

    def startEdit(self):
        super().startEdit()
        self.table.setEditTriggers(TableWidget.AllEditTriggers)
        self.table.item(0, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(1, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(2, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(2, 1).setFlags(Qt.ItemIsEnabled)
        # 重新获得已有课程的周数
        self.other_courses = self.schedule_service.getCourseInCertainTime(self.day_of_week, self.start_time,
                                                                          self.end_time)
        self.other_weeks = [course.week_number for course in self.other_courses]
        self.switchTo(True)

    def checkEdit(self):
        if self.headerEdit.text() == "":
            self.headerEdit.setError(True)
            self.headerEdit.setFocus()
            return
        self.confirmEdit()

    def confirmEdit(self):
        super().confirmEdit()

        name = self.headerEdit.text()
        teacher = self.table.item(0, 1).text()
        location = self.table.item(1, 1).text()
        self.schedule_service.addCourse(name, self.day_of_week, self.start_time, self.end_time,
                                        location, teacher, self.weeks)
        courses = self.schedule_service.getCourseInCertainTime(self.day_of_week, self.start_time, self.end_time)
        current_course = None
        for course in courses:
            if course.week_number == self.current_week:
                current_course = course
                break

        self.switchTo(False)
        self.courseAdded.emit(current_course)

    def cancelEdit(self):
        super().cancelEdit()
        self.table.item(0, 1).setText("")
        self.table.item(1, 1).setText("")
        self.table.item(2, 1).setText("")
        self.headerEdit.clear()
        self.headerLabel.clear()
        self.weeks = []
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.switchTo(False)


class ExamCard(HeaderCardWidget):
    # 此卡片对应的考试被删除时，会发送的信息
    courseDeleted = pyqtSignal(Exam)

    def __init__(self, exam: Exam, start_time: date, service: ScheduleService,
                 on_edit_trigger=None, parent=None):
        """
        创建一个用于展示考试的卡片
        :param exam: 考试对象
        :param start_time: 学期开始时间。如果设置 ambiguous_time 为 True，则直接传入 None 即可。
        :param service: schedule_service 的对象
        :param on_edit_trigger: 当课程被编辑时的回调函数
        :param parent: 父对象
        """
        super().__init__(parent)

        self.exam = exam
        self.editable = False
        self.start_time = start_time
        self.setTitle(exam.name)

        self.on_edit_trigger = on_edit_trigger

        self.schedule_service = service

        self.confirm_flyout = None
        self.delete_flyout = None

        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setRowCount(3)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setWordWrap(True)

        self.viewLayout.addWidget(self.table)

        self.functionFrame = QFrame(self)
        self.functionFrame.setContentsMargins(0, 0, 0, 0)
        self.functionLayout = QHBoxLayout(self.functionFrame)
        self.editButton = TransparentPushButton(FluentIcon.EDIT, self.tr("编辑"), self)
        self.functionLayout.addWidget(self.editButton)
        self.deleteButton = TransparentPushButton(FluentIcon.DELETE, self.tr("删除"), self)
        self.functionLayout.addWidget(self.deleteButton)
        self.editButton.clicked.connect(self.startEdit)
        self.deleteButton.clicked.connect(self.onDeleteClicked)

        self.viewLayout.addWidget(self.functionFrame)

        self.confirmFrame = QFrame(self)
        self.confirmFrame.setContentsMargins(0, 0, 0, 0)
        self.confirmLayout = QHBoxLayout(self.confirmFrame)
        self.confirmButton = TransparentPushButton(FluentIcon.ACCEPT, self.tr("确定"), self)
        self.confirmButton.clicked.connect(self.checkEdit)
        self.confirmLayout.addWidget(self.confirmButton)

        self.cancelButton = TransparentPushButton(FluentIcon.CLOSE, self.tr("取消"), self)
        self.cancelButton.clicked.connect(self.cancelEdit)
        self.confirmLayout.addWidget(self.cancelButton)

        self.viewLayout.addWidget(self.confirmFrame)

        self.other_courses = None
        self.other_weeks = None

        self.loadDataFromExam()

        self.confirmFrame.setVisible(False)
        self.table.setMinimumWidth(400)
        self.table.setMinimumHeight(130)

        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def loadDataFromExam(self):
        """
        按照课程的信息，填充表格。此方法会重置当前课程被修改的信息。
        """
        start_time = self.exam.start_exact_time.strftime("%H:%M")
        end_time = self.exam.end_exact_time.strftime("%H:%M")

        self.table.setItem(0, 0, QTableWidgetItem(self.tr("时间")))
        self.table.setItem(
            0, 1, QTableWidgetItem(f"{start_time} - {end_time}"))
        self.table.setItem(1, 0, QTableWidgetItem(self.tr("地点")))
        self.table.setItem(1, 1, QTableWidgetItem(self.exam.location))
        self.table.setItem(2, 0, QTableWidgetItem(self.tr("座位号")))
        self.table.setItem(2, 1, QTableWidgetItem(self.exam.seat_number))
        self.table.adjustSize()

    @pyqtSlot()
    def startEdit(self):
        super().startEdit()
        self.functionFrame.setVisible(False)
        self.confirmFrame.setVisible(True)

        self.editable = True
        self.table.setEditTriggers(TableWidget.AllEditTriggers)

        # 重新生成其他周课程
        self.other_courses = self.schedule_service.getOtherCourseInSameTime(self.exam)
        self.other_weeks = []
        for course in self.other_courses:
            if isinstance(course.week_numbers, int):
                self.other_weeks.append(course.week_numbers)
            else:
                for one in course.week_numbers.split(","):
                    self.other_weeks.append(int(one))

        self.table.item(0, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(0, 1).setFlags(Qt.ItemIsEnabled)
        self.table.item(1, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(2, 0).setFlags(Qt.ItemIsEnabled)

    @pyqtSlot()
    def checkEdit(self):
        """
        检查当前卡片在编辑状态下被编辑的内容，决定是否要弹出「询问修改单周课程还是全部课程」的浮窗
        """
        self.confirmEdit()

    @pyqtSlot()
    def confirmEdit(self):
        """
        根据编辑后的内容修改考试
        """
        if self.on_edit_trigger is not None:
            self.on_edit_trigger()

        new_name = self.headerEdit.text()
        new_seat_number = self.table.item(2, 1).text()
        new_location = self.table.item(1, 1).text()

        self.schedule_service.editExam(self.exam, new_name, new_location, new_seat_number)
        self.headerLabel.setText(new_name)
        self.finishEdit()

    @pyqtSlot()
    def onDeleteClicked(self):
        self.delete_flyout = Flyout.make(
            target=self.deleteButton,
            view=DeleteAllFlyoutView(),
            parent=self
        )
        self.delete_flyout.view.confirm_button.clicked.connect(self.confirmDelete)
        self.delete_flyout.view.cancel_button.clicked.connect(self.delete_flyout.close)

    @pyqtSlot()
    def confirmDelete(self):
        """
        删除当前时间段在所有周的课程
        """
        self.schedule_service.deleteExam(self.exam)
        self.finishEdit()
        self.delete_flyout.close()
        self.courseDeleted.emit(self.exam)

    def finishEdit(self):
        """
        结束编辑，但不重新加载内容
        """
        self.functionFrame.setVisible(True)
        self.confirmFrame.setVisible(False)

        self.editable = False
        self.headerEdit.setVisible(False)
        self.headerLabel.setVisible(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)

    @pyqtSlot()
    def cancelEdit(self):
        super().cancelEdit()
        self.functionFrame.setVisible(True)
        self.confirmFrame.setVisible(False)

        self.editable = False
        self.table.setEditTriggers(TableWidget.NoEditTriggers)

        self.loadDataFromExam()


class LessonDetailDialog(MessageBoxBase):
    @singledispatchmethod
    def __init__(self, parent=None):
        super().__init__(parent)

    @__init__.register
    def _(self, course: CourseInstance, start_date: date, interface, parent=None):
        """
        创建一个课程详情对话框，且根据输入的课程信息初始化一张课程卡片
        :param course: 作为初识卡片的课程信息
        :param start_date: 学期开始时间
        :param interface: 主界面的对象
        :param parent: 父对象
        """
        super().__init__(parent)

        self.expanded = False
        # 是否已经创建了所有的课程卡片
        self.all_lessons_created = False
        # 是否被修改过（用于决定关闭对话框时，是否要重新加载本周课表）
        # 此属性被自身包含的 LessonCard 修改
        self.modified = False

        self.content = ScrollArea(self)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view = QWidget(self.content)
        self.content_layout = QVBoxLayout(self.view)
        self.content.setStyleSheet("border: none;background-color: transparent;")
        self.view.setStyleSheet("background-color: transparent;")

        self.course = course
        self.start_date = start_date
        self.parent_interface = interface

        self.other_courses = self.parent_interface.schedule_service.getOtherCourseInSameTime(self.course)

        self.lesson_cards = []
        self.on_edit = lambda: setattr(self, "modified", True)
        lesson_card = LessonCard(course, start_date, interface.schedule_service, False, False,
                                 self.on_edit, self)
        lesson_card.courseDeleted.connect(self.onCourseDeleted)
        self.lesson_cards.append(lesson_card)

        self.moreButton = TransparentPushButton(FluentIcon.DOWN, self.tr("展开"), self)
        self.lessButton = TransparentPushButton(FluentIcon.UP, self.tr("收起"), self)
        self.moreButton.clicked.connect(self.onExpandClicked)
        self.lessButton.clicked.connect(self.onExpandClicked)
        if not self.other_courses:
            self.moreButton.setVisible(False)
            self.lessButton.setVisible(False)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.content_layout.addWidget(lesson_card)
        self.content_layout.addWidget(self.moreButton)
        self.content_layout.addWidget(self.lessButton)
        self.lessButton.setVisible(False)

        self.content.setWidget(self.view)
        self.content.setWidgetResizable(True)

        self.viewLayout.addWidget(self.content)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)

        self.content.setMinimumHeight(350)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

    @__init__.register
    def _(self, week: int, day_of_week: int, start_time: int, end_time: int, start_date: Optional[date], interface,
          parent=None):
        """
        创建一个课程详情对话框，且包含一张空白的课程卡片
        :param week: 对话框表示第几周的课程
        :param day_of_week: 对话框表示星期几的课程
        :param start_time: 对话框表示的课程开始时间
        :param end_time: 对话框表示的课程结束时间
        :param start_date: 学期开始时间，可以为空
        :param interface: 主界面的对象
        :param parent: 父对象
        """
        super().__init__(parent)

        self.expanded = False
        self.all_lessons_created = False
        self.modified = False

        self.content = ScrollArea(self)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view = QWidget(self.content)
        self.content_layout = QVBoxLayout(self.view)
        self.content.setStyleSheet("border: none;background-color: transparent;")
        self.view.setStyleSheet("background-color: transparent;")

        self.parent_interface = interface
        self.start_date = start_date

        self.lesson_cards = []
        self.on_edit = lambda: setattr(self, "modified", True)
        lesson_card = EmptyLessonCard(week, day_of_week, start_time, end_time, self.parent_interface.schedule_service,
                                      self)
        self.lesson_cards.append(lesson_card)

        self.other_courses = self.parent_interface.schedule_service.getCourseGroupInCertainTime(day_of_week, start_time,
                                                                                                end_time)

        self.moreButton = TransparentPushButton(FluentIcon.DOWN, self.tr("展开"), self)
        self.lessButton = TransparentPushButton(FluentIcon.UP, self.tr("收起"), self)
        self.moreButton.clicked.connect(self.onExpandClicked)
        self.lessButton.clicked.connect(self.onExpandClicked)
        if not self.other_courses:
            self.moreButton.setVisible(False)
            self.lessButton.setVisible(False)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.content_layout.addWidget(lesson_card)
        self.content_layout.addWidget(self.moreButton)
        self.content_layout.addWidget(self.lessButton)
        self.lessButton.setVisible(False)

        self.content.setWidget(self.view)
        self.content.setWidgetResizable(True)

        self.viewLayout.addWidget(self.content)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)

        self.content.setMinimumHeight(350)

        lesson_card.courseAdded.connect(self.onCourseAdded)
        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

    @__init__.register
    def _(self, exam: Exam, start_date: date, interface, parent=None):
        """
        创建一个课程详情对话框，且根据输入的考试信息初始化一张考试卡片
        :param exam: 作为初始卡片的考试信息
        :param start_date: 学期开始时间
        :param interface: 主界面的对象
        :param parent: 父对象
        """
        super().__init__(parent)

        self.expanded = False
        # 是否已经创建了所有的课程卡片
        self.all_lessons_created = False
        # 是否被修改过（用于决定关闭对话框时，是否要重新加载本周课表）
        # 此属性被自身包含的 LessonCard 修改
        self.modified = False

        self.content = ScrollArea(self)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view = QWidget(self.content)
        self.content_layout = QVBoxLayout(self.view)
        self.content.setStyleSheet("border: none;background-color: transparent;")
        self.view.setStyleSheet("background-color: transparent;")

        self.course = exam
        self.start_date = start_date
        self.parent_interface = interface

        self.other_courses = self.parent_interface.schedule_service.getOtherCourseInSameTime(self.course)

        self.lesson_cards = []
        self.on_edit = lambda: setattr(self, "modified", True)
        lesson_card = ExamCard(exam, start_date, interface.schedule_service, self.on_edit, self)
        lesson_card.courseDeleted.connect(self.onCourseDeleted)
        self.lesson_cards.append(lesson_card)

        self.moreButton = TransparentPushButton(FluentIcon.DOWN, self.tr("展开"), self)
        self.lessButton = TransparentPushButton(FluentIcon.UP, self.tr("收起"), self)
        self.moreButton.clicked.connect(self.onExpandClicked)
        self.lessButton.clicked.connect(self.onExpandClicked)
        if not self.other_courses:
            self.moreButton.setVisible(False)
            self.lessButton.setVisible(False)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.content_layout.addWidget(lesson_card)
        self.content_layout.addWidget(self.moreButton)
        self.content_layout.addWidget(self.lessButton)
        self.lessButton.setVisible(False)

        self.content.setWidget(self.view)
        self.content.setWidgetResizable(True)

        self.viewLayout.addWidget(self.content)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)

        self.content.setMinimumHeight(300)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

    @pyqtSlot()
    def onExpandClicked(self):
        self.expanded = not self.expanded
        self.moreButton.setVisible(not self.expanded)
        self.lessButton.setVisible(self.expanded)
        if self.expanded:
            if not self.all_lessons_created:
                self.content_layout.removeWidget(self.moreButton)
                self.content_layout.removeWidget(self.lessButton)
                for course in self.other_courses:
                    lesson_card = LessonCard(course, self.start_date, self.parent_interface.schedule_service,
                                             True, True, self.on_edit, self)
                    lesson_card.courseDeleted.connect(self.onCourseDeleted)
                    self.lesson_cards.append(lesson_card)
                    self.content_layout.addWidget(lesson_card)
                self.all_lessons_created = True
                self.content_layout.addWidget(self.moreButton)
                self.content_layout.addWidget(self.lessButton)
            for lesson_card in self.lesson_cards:
                lesson_card.setVisible(True)
        else:
            for lesson_card in self.lesson_cards:
                lesson_card.setVisible(False)
            # 只保留第一个课程卡片
            self.lesson_cards[0].setVisible(True)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        self.close()
        self.reject()

    def __del__(self):
        accounts.currentAccountChanged.disconnect(self.onCurrentAccountChanged)

    @pyqtSlot(CourseInstance)
    def onCourseAdded(self, course):
        card = self.lesson_cards.pop(0)
        card.setVisible(False)
        lesson_card = LessonCard(course, self.start_date, self.parent_interface.schedule_service, False,
                                 False, self.on_edit, self)
        lesson_card.courseDeleted.connect(self.onCourseDeleted)
        self.lesson_cards.append(lesson_card)
        self.content_layout.insertWidget(1, lesson_card)
        self.lesson_cards[0].setVisible(True)
        self.modified = True

    @pyqtSlot(object)
    def onCourseDeleted(self, course):
        card_number = -1
        for card in self.lesson_cards:
            card_number += 1
            if hasattr(card, "exam") and self.checkSameCourse(card.exam, course) or hasattr(card, "course") and self.checkSameCourse(card.course, course):
                card.setVisible(False)
                self.lesson_cards.remove(card)
                self.content_layout.removeWidget(card)
                break

        self.modified = True
        if card_number == 0:
            # 如果删除了第一张卡片，那么放置一张空白课程卡
            lesson_card = EmptyLessonCard(course.week_number, course.day_of_week, course.start_time, course.end_time,
                                          self.parent_interface.schedule_service, self)
            self.lesson_cards.insert(0, lesson_card)
            self.content_layout.insertWidget(1, lesson_card)
            lesson_card.setVisible(True)
        # 重新获得其他课程列表
        if hasattr(self, "course"):
            self.other_courses = self.parent_interface.schedule_service.getOtherCourseInSameTime(self.course)
        else:
            self.other_courses = self.parent_interface.schedule_service.getCourseGroupInCertainTime(course.day_of_week,
                                                                                                    course.start_time,
                                                                                                    course.end_time)
        if len(self.other_courses) == 0:
            self.expanded = False
            self.moreButton.setVisible(False)
            self.lessButton.setVisible(False)

    def checkSameCourse(self, course1, course2):
        return (course1.name == course2.name
                and course1.start_time == course2.start_time
                and course1.end_time == course2.end_time
                and course1.day_of_week == course2.day_of_week
                and course1.term_number == course2.term_number)
