from typing import List

from PyQt5.QtWidgets import QHeaderView, QTableWidgetItem
from qfluentwidgets import HeaderCardWidget, TableWidget

from schedule.schedule_database import CourseInstance


class PureLessonCard(HeaderCardWidget):
    def __init__(self, course: CourseInstance, week_numbers: List = None, parent=None):
        """
        创建一张课程展示卡片
        :param course: 需要展示的课程
        :param week_numbers: 如果此项目不是 None，课程的「上课周」部分将会展示为 week_numbers
        :param parent:
        """
        super().__init__(parent)

        self.weekdays_dict = {
            1: self.tr("星期一"),
            2: self.tr("星期二"),
            3: self.tr("星期三"),
            4: self.tr("星期四"),
            5: self.tr("星期五"),
            6: self.tr("星期六"),
            7: self.tr("星期日"),
        }
        self.course = course
        self.week_numbers = week_numbers

        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setRowCount(4)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setWordWrap(False)

        self.loadFromCourse(self.course, self.week_numbers)
        self.viewLayout.addWidget(self.table)

    def loadFromCourse(self, course=None, week_numbers=None):
        if course is None:
            course = self.course
        if week_numbers is None:
            week_numbers = self.week_numbers

        self.setTitle(course.name)
        self.table.setItem(0, 0, QTableWidgetItem(self.tr("时间")))
        self.table.setItem(0, 1, QTableWidgetItem(f"{self.weekdays_dict[course.day_of_week]} {course.start_time} - {course.end_time} {self.tr("节")}"))
        self.table.setItem(1, 0, QTableWidgetItem(self.tr("教师")))
        self.table.setItem(1, 1, QTableWidgetItem(course.teacher))
        self.table.setItem(2, 0, QTableWidgetItem(self.tr("地点")))
        self.table.setItem(2, 1, QTableWidgetItem(course.location))
        self.table.setItem(3, 0, QTableWidgetItem(self.tr("上课周")))
        if week_numbers is not None:
            self.table.setItem(3, 1, QTableWidgetItem(",".join(map(str, week_numbers))))
        else:
            self.table.setItem(3, 1, QTableWidgetItem(course.week_number))
