from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QSizePolicy, QTableWidgetItem
from qfluentwidgets import TableWidget

from .common import PageStatus, create_loading_frame, create_retry_frame, apply_full_width_column_width, update_table_height, bool_text


class LMSCoursePage(QFrame):
    # 用户点击课程行后，通知主容器当前选择的课程 ID 与课程名。
    courseSelected = pyqtSignal(int, str)
    # 用户点击重试按钮后，请求主容器重新加载课程。
    retryRequested = pyqtSignal()

    def __init__(self, parent=None):
        """初始化课程页组件与表格。"""
        super().__init__(parent)
        self.setObjectName("coursePage")
        self._courses: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.courseTable = TableWidget(self)
        self.courseTable.setRowCount(0)
        self.courseTable.setColumnCount(6)
        self.courseTable.setHorizontalHeaderLabels([
            self.tr("课程"), self.tr("学年学期"), self.tr("任课教师"), self.tr("学分"), self.tr("发布"), self.tr("教学班")
        ])
        apply_full_width_column_width(self.courseTable)
        self.courseTable.verticalHeader().setVisible(False)
        self.courseTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.courseTable.setMinimumHeight(0)
        self.courseTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.courseTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.courseTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.courseTable.cellClicked.connect(self._onCourseClicked)

        self.loadingFrame = create_loading_frame(self)
        self.loadingFrame.setVisible(False)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

        layout.addWidget(self.courseTable)
        layout.addWidget(self.loadingFrame)
        layout.addWidget(self.failFrame)

        update_table_height(self.courseTable, min_rows=1, min_height=140)

    def setPageStatus(self, status: PageStatus):
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            self.loadingFrame.setVisible(True)
            self.courseTable.setVisible(False)
            self.failFrame.setVisible(False)
            return
        if status == PageStatus.ERROR:
            self.loadingFrame.setVisible(False)
            self.courseTable.setVisible(False)
            self.failFrame.setVisible(True)
            return

        self.loadingFrame.setVisible(False)
        self.courseTable.setVisible(True)
        self.failFrame.setVisible(False)

    def setCourses(self, courses: list[dict]):
        """填充课程表格数据。

        :param courses: 课程列表，每项为课程字典。
        :return: 无返回值。
        """
        self._courses = courses if isinstance(courses, list) else []
        self.courseTable.setRowCount(len(self._courses))

        for row, course in enumerate(self._courses):
            semester = course.get("semester", {}) if isinstance(course.get("semester"), dict) else {}
            academic_year = course.get("academic_year", {}) if isinstance(course.get("academic_year"), dict) else {}
            course_attr = course.get("course_attributes", {}) if isinstance(course.get("course_attributes"), dict) else {}
            instructors = course.get("instructors", []) if isinstance(course.get("instructors"), list) else []
            instructor_text = "、".join(str(one.get("name", "")) for one in instructors if isinstance(one, dict) and one.get("name"))
            semester_text = f"{academic_year.get('name') or '-'} {semester.get('name') or semester.get('real_name') or '-'}"

            self.courseTable.setItem(row, 0, QTableWidgetItem(str(course.get("name") or "-")))
            self.courseTable.setItem(row, 1, QTableWidgetItem(semester_text.strip()))
            self.courseTable.setItem(row, 2, QTableWidgetItem(instructor_text or "-"))
            self.courseTable.setItem(row, 3, QTableWidgetItem(str(course.get("credit") or "-")))
            self.courseTable.setItem(row, 4, QTableWidgetItem(bool_text(course_attr.get("published"))))
            self.courseTable.setItem(row, 5, QTableWidgetItem(str(course_attr.get("teaching_class_name") or "-")))

        self.courseTable.resizeRowsToContents()
        update_table_height(self.courseTable, min_rows=1, min_height=140)

    def clearData(self):
        """清空课程数据与表格内容。

        :return: 无返回值。
        """
        self._courses = []
        self.courseTable.setRowCount(0)
        update_table_height(self.courseTable, min_rows=1, min_height=140)

    def reset(self):
        """重置课程页到初始状态。

        :return: 无返回值。
        """
        self.clearData()
        self.setPageStatus(PageStatus.NORMAL)

    def setInteractionEnabled(self, enabled: bool):
        """设置课程表格是否可交互。

        :param enabled: 为 True 时允许选择课程；为 False 时禁用表格操作。
        :return: 无返回值。
        """
        self.courseTable.setEnabled(enabled)

    def _onCourseClicked(self, row: int, _column: int):
        """处理课程表格点击事件并发出课程选择信号。"""
        if row < 0 or row >= len(self._courses):
            return
        course = self._courses[row]
        course_id = course.get("id")
        if not isinstance(course_id, int):
            return
        self.courseSelected.emit(course_id, str(course.get("name") or "-"))
