from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import ComboBox, LineEdit, PrimaryPushButton

from jwxt.school_course import CAMPUS_OPTIONS, ELECTIVE_OPTIONS, SchoolCourseQuery
from .components.CampusPage import CampusPage


class SchoolCourseInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("schoolCourseInterface", "全校课程", "按课名、学院、校区检索开课", parent)
        self._terms_loaded = False
        self.departments = []

        self.termBox = ComboBox(self.view)
        self.termBox.setMinimumWidth(200)
        self.campusBox = ComboBox(self.view)
        for code, name in CAMPUS_OPTIONS.items():
            self.campusBox.addItem(name, userData=code)
        self.electiveBox = ComboBox(self.view)
        for code, name in ELECTIVE_OPTIONS.items():
            self.electiveBox.addItem(name, userData=code)
        self.deptBox = ComboBox(self.view)
        self.deptBox.setMinimumWidth(180)
        self.deptBox.addItem(self.tr("全部单位"), userData="")
        self.add_toolbar(
            self.labeled(self.tr("学期"), self.termBox),
            self.labeled(self.tr("校区"), self.campusBox, width=40),
            self.labeled(self.tr("选修"), self.electiveBox, width=40),
            self.labeled(self.tr("开课单位"), self.deptBox, width=64),
        )

        self.nameEdit = LineEdit(self.view)
        self.nameEdit.setPlaceholderText(self.tr("课程名，可留空"))
        self.nameEdit.setMinimumWidth(220)
        self.nameEdit.returnPressed.connect(self.query)
        self.queryButton = PrimaryPushButton(self.tr("查询"), self.view)
        self.queryButton.setFixedWidth(96)
        self.queryButton.clicked.connect(self.query)
        self.add_toolbar(self.labeled(self.tr("课名"), self.nameEdit, width=40), self.queryButton)

        self.table = self.make_table([
            self.tr("课程"), self.tr("教师"), self.tr("开课单位"), self.tr("学分"),
            self.tr("校区"), self.tr("容量"), self.tr("时间地点"),
        ])
        self.vBoxLayout.addWidget(self.table, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._terms_loaded:
            return
        self._terms_loaded = True
        self.load_terms()

    def load_terms(self):
        if not self.require_account():
            self._terms_loaded = False
            return

        def worker(session):
            util = SchoolCourseQuery(session)
            return util.term_list(), util.current_term(), util.departments()

        self.start_job("jwxt", self.tr("正在登录教务系统..."), worker, self._on_terms)

    def _on_terms(self, payload):
        terms, current, departments = payload
        self.termBox.clear()
        current_index = 0
        for index, (code, name) in enumerate(terms):
            self.termBox.addItem(name or code, userData=code)
            if code == current:
                current_index = index
        if terms:
            self.termBox.setCurrentIndex(current_index)
        self.departments = departments
        self.deptBox.clear()
        self.deptBox.addItem(self.tr("全部单位"), userData="")
        for code, name in departments:
            self.deptBox.addItem(name, userData=code)
        self.success(self.tr("加载成功"), self.tr("已更新学期与开课单位"))

    def query(self):
        if not self.require_account():
            return
        term = self.termBox.currentData()
        if not term:
            self.warn(self.tr("未选择学期"), self.tr("学期列表还没加载完，请稍后再查"))
            return

        def worker(session):
            return SchoolCourseQuery(session).query(
                term=term,
                course_name=self.nameEdit.text().strip(),
                department=self.deptBox.currentData() or "",
                campus=self.campusBox.currentData() or "",
                elective=self.electiveBox.currentData() or "",
                page_size=50,
            )

        self.start_job("jwxt", self.tr("正在查询课程..."), worker, self._on_result)

    def _on_result(self, payload):
        total, courses = payload
        self.table.setRowCount(len(courses))
        for row, course in enumerate(courses):
            title = course.course_name
            if course.course_code:
                title = f"{course.course_name}（{course.course_code}）"
            self.table.setItem(row, 0, QTableWidgetItem(title))
            self.table.setItem(row, 1, QTableWidgetItem(course.teachers))
            self.table.setItem(row, 2, QTableWidgetItem(course.department))
            self.table.setItem(row, 3, QTableWidgetItem(course.credit))
            self.table.setItem(row, 4, QTableWidgetItem(course.campus))
            self.table.setItem(row, 5, QTableWidgetItem(f"{course.selected}/{course.capacity}"))
            self.table.setItem(row, 6, QTableWidgetItem(course.time_place))
        self.table.resizeRowsToContents()
        self.success(self.tr("查询成功"), self.tr("共 {total} 门，本页 {count} 门").format(total=total, count=len(courses)))
