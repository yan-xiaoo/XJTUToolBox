from datetime import date, timedelta

from PyQt5.QtCore import pyqtProperty, Qt, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QVBoxLayout, QWidget, QLabel, QHBoxLayout, QTableWidgetItem, QHeaderView, QFrame
from qfluentwidgets import MessageBoxBase, SimpleCardWidget, setFont, FluentStyleSheet, \
    FluentIcon, TransparentPushButton, TableWidget, ScrollArea, FlyoutViewBase, FlowLayout, \
    CheckBox, Flyout, LineEdit, PrimaryPushButton, PushButton
from qfluentwidgets.common.overload import singledispatchmethod
from qfluentwidgets.components.widgets.card_widget import CardSeparator

from app.utils import accounts
from schedule import getClassStartTime, getClassEndTime
from schedule.schedule_database import CourseInstance, CourseStatus
from schedule.schedule_service import ScheduleService
from schedule.xjtu_time import isSummerTime


class WeekFlyoutView(FlyoutViewBase):
    def __init__(self, weeks, parent=None):
        super().__init__(parent)
        self.weeks = set(weeks)
        self.weeksLayout = FlowLayout(self)
        self.weeksLayout.setSpacing(8)
        self.checkbox = []
        self.setMinimumWidth(300)

        for week in range(1, 19):
            checkbox = CheckBox(f"第{week}周", self)
            checkbox.setMinimumWidth(150)
            checkbox.setChecked(week in self.weeks)
            checkbox.stateChanged.connect(self.onWeekChanged)
            self.weeksLayout.addWidget(checkbox)
            self.checkbox.append(checkbox)

    def onWeekChanged(self, state):
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
    def __init__(self, course: CourseInstance, start_time: date, service: ScheduleService, ambiguous_time=False, on_edit_trigger=None, parent=None):
        """
        创建一个用于展示课程的卡片
        :param course: 课程对象
        :param start_time: 学期开始时间
        :param service: schedule_service 的对象
        :param ambiguous_time: 是否使用模糊时间。如果是，则只显示课程开始-结束节次，不显示具体时间。
        如果需要显示具体时间（False），那么 course 的 week 属性不能为 None。
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

        self.loadDataFromCourse()
        self.table.cellClicked.connect(self.onTableWidgetClicked)

        self.confirmFrame.setVisible(False)
        self.table.setMinimumWidth(400)

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
        if self.ambiguous_time:
            class_start_time = self.course.start_time
            class_end_time = self.course.end_time
        else:
            is_summer_time = isSummerTime(
                self.start_time + timedelta(days=((self.course.week_number - 1) * 7 + self.course.day_of_week - 1)))
            class_start_time = getClassStartTime(self.course.start_time, is_summer_time).strftime("%H:%M")
            class_end_time = getClassEndTime(self.course.end_time, is_summer_time).strftime("%H:%M")

        self.weeks = self.getAllWeeks()
        weeks = [str(week) for week in self.weeks]

        if self.ambiguous_time:
            self.table.setRowHidden(0, True)
        else:
            self.table.setItem(0, 0, QTableWidgetItem(self.tr("状态")))
            self.table.setItem(0, 1, QTableWidgetItem(self.status_dict.get(CourseStatus(self.course.status), self.tr("未知"))))
        self.table.setItem(1, 0, QTableWidgetItem(self.tr("时间")))
        self.table.setItem(1, 1, QTableWidgetItem(f"{class_start_time} - {class_end_time}"))
        self.table.setItem(2, 0, QTableWidgetItem(self.tr("教师")))
        self.table.setItem(2, 1, QTableWidgetItem(self.course.teacher))
        self.table.setItem(3, 0, QTableWidgetItem(self.tr("地点")))
        self.table.setItem(3, 1, QTableWidgetItem(self.course.location))
        self.table.setItem(4, 0, QTableWidgetItem(self.tr("上课周")))
        self.table.setItem(4, 1, QTableWidgetItem(f"{",".join(weeks)}"))
        self.table.adjustSize()

    @pyqtSlot()
    def startEdit(self):
        super().startEdit()
        self.functionFrame.setVisible(False)
        self.confirmFrame.setVisible(True)

        self.editable = True
        self.table.setEditTriggers(TableWidget.AllEditTriggers)

        if not self.table.isRowHidden(0):
            self.table.item(0, 0).setFlags(Qt.ItemIsEnabled)
            self.table.item(0, 1).setFlags(Qt.ItemIsEnabled)

        self.table.item(1, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(1, 1).setFlags(Qt.ItemIsEnabled)
        self.table.item(2, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(3, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(4, 0).setFlags(Qt.ItemIsEnabled)
        self.table.item(4, 1).setFlags(Qt.ItemIsEnabled)

    @pyqtSlot(int, int)
    def onTableWidgetClicked(self, row, col):
        if row == 4 and col == 1:
            if self.editable:
                self.weeks_flyout = Flyout.make(
                    target=self.table,
                    view=WeekFlyoutView(weeks=self.weeks),
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
        self.confirmWeekEdit()
        self.confirm_flyout.close()

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


class LessonDetailDialog(MessageBoxBase):
    def __init__(self, course: CourseInstance, start_time: date, interface, parent=None):
        super().__init__(parent)

        self.expanded = False
        # 是否已经创建了所有的课程卡片
        self.all_lessons_created = False
        # 是否被修改过（用于决定关闭对话框时，是否要重新加载本周课表）
        # 此属性被自身包含的 LessonCard 修改
        self.modified = False

        self.content = ScrollArea(self)
        self.view = QWidget(self.content)
        self.content_layout = QVBoxLayout(self.view)
        self.content.setStyleSheet("border: none;background-color: transparent;")
        self.view.setStyleSheet("background-color: transparent;")

        self.course = course
        self.start_time = start_time
        self.parent_interface = interface

        self.other_courses = self.parent_interface.schedule_service.getOtherCourseInSameTime(self.course)

        self.lesson_cards = []
        self.on_edit = lambda: setattr(self, "modified", True)
        lesson_card = LessonCard(course, start_time, interface.schedule_service, False, self.on_edit, self)
        self.lesson_cards.append(lesson_card)

        if self.other_courses:
            self.moreButton = TransparentPushButton(FluentIcon.DOWN, self.tr("展开"), self)
            self.lessButton = TransparentPushButton(FluentIcon.UP, self.tr("收起"), self)
            self.moreButton.clicked.connect(self.onExpandClicked)
            self.lessButton.clicked.connect(self.onExpandClicked)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.content_layout.addWidget(lesson_card)
        if self.other_courses:
            self.content_layout.addWidget(self.moreButton)
            self.content_layout.addWidget(self.lessButton)
            self.lessButton.setVisible(False)

        self.content.setWidget(self.view)
        self.content.setWidgetResizable(True)

        self.viewLayout.addWidget(self.content)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)

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
                    lesson_card = LessonCard(course, self.start_time, self.parent_interface.schedule_service,
                                             True, self.on_edit, self)
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
