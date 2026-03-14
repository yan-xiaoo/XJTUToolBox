import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QActionGroup, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import Action, CheckableMenu, ComboBox, FluentIcon, FlowLayout, MenuIndicatorType, TransparentDropDownPushButton

from .common import PageStatus, create_retry_frame
from app.cards.course_card import LMSCourseCard, CourseSkeletonCard


class LMSCoursePage(QFrame):
    # 用户点击课程卡片后，通知主容器当前选择的课程 ID 与课程名。
    courseSelected = pyqtSignal(int, str)
    # 用户点击重试按钮后，请求主容器重新加载课程。
    retryRequested = pyqtSignal()
    _FILTER_ALL_KEY = "__ALL__"

    def __init__(self, parent=None):
        """初始化课程页组件与布局。"""
        super().__init__(parent)
        self.setObjectName("coursePage")

        # 存储目前已经获得的课程信息
        self._all_courses: list[dict] = []
        self._visible_courses: list[dict] = []
        self._skeleton_cards = []
        self._course_cards = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.filterFrame = QFrame(self)
        self.filterLayout = QHBoxLayout(self.filterFrame)
        self.filterLayout.setContentsMargins(0, 0, 0, 0)
        self.filterLayout.setSpacing(12)

        self.termFilterComboBox = ComboBox(self.filterFrame)
        self.termFilterComboBox.setMinimumWidth(220)
        self.termFilterComboBox.currentIndexChanged.connect(self._onFilterChanged)
        self.filterLayout.addWidget(self.termFilterComboBox, alignment=Qt.AlignLeft)

        self.sortButton = TransparentDropDownPushButton(FluentIcon.SYNC, self.tr("排序方式"), self.filterFrame)
        self.sortButton.setFixedHeight(34)

        self.nameSortGroup = QActionGroup(self)
        self.nameAscAction = Action(FluentIcon.UP, self.tr("课程名 A→Z"), self, checkable=True)
        self.nameDescAction = Action(FluentIcon.DOWN, self.tr("课程名 Z→A"), self, checkable=True)
        self.nameSortGroup.addAction(self.nameAscAction)
        self.nameSortGroup.addAction(self.nameDescAction)

        self.termSortGroup = QActionGroup(self)
        self.termNewToOldAction = Action(FluentIcon.UP, self.tr("学期 新→旧"), self, checkable=True)
        self.termOldToNewAction = Action(FluentIcon.DOWN, self.tr("学期 旧→新"), self, checkable=True)
        self.termSortGroup.addAction(self.termNewToOldAction)
        self.termSortGroup.addAction(self.termOldToNewAction)

        self.nameAscAction.setChecked(True)
        self.termNewToOldAction.setChecked(True)

        self.nameAscAction.triggered.connect(self._onSortChanged)
        self.nameDescAction.triggered.connect(self._onSortChanged)
        self.termNewToOldAction.triggered.connect(self._onSortChanged)
        self.termOldToNewAction.triggered.connect(self._onSortChanged)

        self.sortMenu = CheckableMenu(parent=self, indicatorType=MenuIndicatorType.RADIO)
        self.sortMenu.addActions([self.nameAscAction, self.nameDescAction])
        self.sortMenu.addSeparator()
        self.sortMenu.addActions([self.termNewToOldAction, self.termOldToNewAction])
        self.sortButton.setMenu(self.sortMenu)

        self.filterLayout.addStretch(1)
        self.filterLayout.addWidget(self.sortButton, alignment=Qt.AlignRight)
        self.filterFrame.setVisible(False)

        self.cardHost = QWidget(self)
        self.flowLayout = FlowLayout(self.cardHost, needAni=True)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setVerticalSpacing(16)
        self.flowLayout.setHorizontalSpacing(16)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

        layout.addWidget(self.filterFrame)
        layout.addWidget(self.cardHost)
        layout.addWidget(self.failFrame)

    def setPageStatus(self, status: PageStatus):
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            # 加载时，隐藏重试按钮，显示骨架屏
            self.failFrame.setVisible(False)
            self.filterFrame.setVisible(False)
            self.cardHost.setVisible(True)
            self._showSkeletons()
        elif status == PageStatus.ERROR:
            # 出现错误时，清除所有课程卡片，显示重试按钮    
            self.failFrame.setVisible(True)
            self.filterFrame.setVisible(False)
            self.cardHost.setVisible(False)
            self.clearData()
        elif status == PageStatus.NORMAL:
            # 正常显示课程卡片
            self.failFrame.setVisible(False)
            self.filterFrame.setVisible(True)
            self.cardHost.setVisible(True)
            self._hideSkeletons()

    def _showSkeletons(self):
        """显示加载骨架屏。"""
        self.clearData()
        for _ in range(4):
            skeleton = CourseSkeletonCard(self.cardHost)
            self.flowLayout.addWidget(skeleton)
            self._skeleton_cards.append(skeleton)

    def _hideSkeletons(self):
        """隐藏并清理骨架屏。"""
        for skeleton in self._skeleton_cards:
            self.flowLayout.removeWidget(skeleton)
            skeleton.deleteLater()
        self._skeleton_cards.clear()

    def setCourses(self, courses: list[dict]):
        """填充课程卡片数据。

        :param courses: 课程列表，每项为课程字典。
        :return: 无返回值。
        """
        self._clearCourseCards()
        self._hideSkeletons()

        self._all_courses = courses if isinstance(courses, list) else []
        self._rebuildFilterItems()
        self._applyCurrentFilter()

    def _clearCourseCards(self):
        """仅清除课程卡片，不影响原始数据与筛选项。"""
        for card in self._course_cards:
            self.flowLayout.removeWidget(card)
            card.deleteLater()
        self._course_cards.clear()

    def _renderCourses(self, courses: list[dict]):
        """根据课程列表重绘课程卡片。"""
        self._clearCourseCards()
        self._visible_courses = courses

        for course in self._visible_courses:
            card = LMSCourseCard(course, self.cardHost)
            card.clicked.connect(
                lambda _=False, cid=card.course_id, cname=card.course_name: self.courseSelected.emit(cid, cname)
            )
            self.flowLayout.addWidget(card)
            self._course_cards.append(card)

    @staticmethod
    def _academicYearFromTermCode(term_code: str) -> str:
        """从形如 YYYY-YYYY-T 的学期码中提取学年部分。"""
        match = re.match(r"^(\d{4}-\d{4})-\d+$", str(term_code or "").strip())
        return match.group(1) if match else ""

    @staticmethod
    def _courseTermMeta(course: dict) -> dict:
        """提取课程的筛选元信息。"""
        semester = course.get("semester", {}) if isinstance(course.get("semester"), dict) else {}
        academic_year = course.get("academic_year", {}) if isinstance(course.get("academic_year"), dict) else {}

        semester_code = str(semester.get("code") or "").strip()
        if semester_code:
            match = re.match(r"^(\d{4})-(\d+)$", semester_code)
            if match:
                start_year = int(match.group(1))
                term = int(match.group(2))
                academic_year_code = f"{start_year}-{start_year + 1}"
                return {
                    "term_code": f"{academic_year_code}-{term}",
                    "academic_year": academic_year_code,
                    "has_semester": True,
                }

        year_name = str(academic_year.get("name") or "").strip()
        return {
            "term_code": "",
            "academic_year": year_name,
            "has_semester": False,
        }

    @staticmethod
    def _termSortKey(term_code: str) -> tuple[int, int, int]:
        """计算学期码排序键，数值越大表示时间越新。"""
        match = re.match(r"^(\d{4})-(\d{4})-(\d+)$", str(term_code or "").strip())
        if not match:
            return -1, -1, -1
        return int(match.group(1)), int(match.group(2)), int(match.group(3))

    @staticmethod
    def _academicYearSortKey(academic_year: str) -> tuple[int, int]:
        """计算学年排序键。"""
        match = re.match(r"^(\d{4})-(\d{4})$", str(academic_year or "").strip())
        if not match:
            return -1, -1
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _courseNameSortKey(course: dict) -> str:
        """课程名称排序键。"""
        return str(course.get("name") or "").casefold()

    def _courseTermSortKey(self, course: dict) -> tuple[int, int, int]:
        """课程学期排序键。"""
        meta = self._courseTermMeta(course)
        if meta["has_semester"] and meta["term_code"]:
            return self._termSortKey(meta["term_code"])

        year_start, year_end = self._academicYearSortKey(meta["academic_year"])
        if year_start < 0 or year_end < 0:
            return -1, -1, -1
        return year_start, year_end, 0

    def _isAllTermSelected(self) -> bool:
        """当前筛选是否为“全部课程”。"""
        current_key = self.termFilterComboBox.currentData()
        return current_key in (None, "", self._FILTER_ALL_KEY)

    def _updateSortMenuAvailability(self):
        """根据筛选状态更新学期排序项可用性。"""
        enable_term_sort = self._isAllTermSelected()
        self.termNewToOldAction.setEnabled(enable_term_sort)
        self.termOldToNewAction.setEnabled(enable_term_sort)

    def _sortCourses(self, courses: list[dict]) -> list[dict]:
        """按当前排序规则返回排序后的课程列表。"""
        sorted_courses = list(courses)

        name_reverse = self.nameDescAction.isChecked()
        sorted_courses.sort(key=self._courseNameSortKey, reverse=name_reverse)

        if self._isAllTermSelected():
            term_reverse = self.termNewToOldAction.isChecked()
            sorted_courses.sort(key=self._courseTermSortKey, reverse=term_reverse)

        return sorted_courses

    def _rebuildFilterItems(self):
        """重建筛选框选项，仅包含有课程的学年-学期。"""
        term_codes = set()
        for course in self._all_courses:
            meta = self._courseTermMeta(course)
            if meta["has_semester"] and meta["term_code"]:
                term_codes.add(meta["term_code"])

        sorted_terms = sorted(term_codes, key=self._termSortKey, reverse=True)

        self.termFilterComboBox.blockSignals(True)
        self.termFilterComboBox.clear()
        self.termFilterComboBox.addItem(self.tr("全部课程"), userData=self._FILTER_ALL_KEY)
        for term in sorted_terms:
            self.termFilterComboBox.addItem(term, userData=term)
        self.termFilterComboBox.setCurrentIndex(0)
        self.termFilterComboBox.blockSignals(False)

    def _applyCurrentFilter(self):
        """按当前筛选与排序条件刷新可见课程。"""
        self._updateSortMenuAvailability()

        current_key = self.termFilterComboBox.currentData()
        if current_key in (None, ""):
            current_key = self._FILTER_ALL_KEY

        if current_key == self._FILTER_ALL_KEY:
            self._renderCourses(self._sortCourses(self._all_courses))
            return

        selected_academic_year = self._academicYearFromTermCode(str(current_key))
        filtered_courses: list[dict] = []
        for course in self._all_courses:
            meta = self._courseTermMeta(course)
            if meta["has_semester"]:
                if meta["term_code"] == current_key:
                    filtered_courses.append(course)
            else:
                if selected_academic_year and meta["academic_year"] == selected_academic_year:
                    filtered_courses.append(course)

        self._renderCourses(self._sortCourses(filtered_courses))

    def _onFilterChanged(self, _index: int):
        """处理筛选项切换。"""
        self._applyCurrentFilter()

    def _onSortChanged(self):
        """处理排序项切换。"""
        self._applyCurrentFilter()

    def clearData(self):
        """清空课程数据与卡片内容。

        :return: 无返回值。
        """
        self._clearCourseCards()
        self._hideSkeletons()
        self._all_courses = []
        self._visible_courses = []

        self.termFilterComboBox.blockSignals(True)
        self.termFilterComboBox.clear()
        self.termFilterComboBox.addItem(self.tr("全部课程"), userData=self._FILTER_ALL_KEY)
        self.termFilterComboBox.setCurrentIndex(0)
        self.termFilterComboBox.blockSignals(False)
        self._updateSortMenuAvailability()

    def reset(self):
        """重置课程页到初始状态。

        :return: 无返回值。
        """
        self.clearData()
        self.setPageStatus(PageStatus.NORMAL)

    def setInteractionEnabled(self, enabled: bool):
        """设置课程卡片是否可交互（如在加载其他数据时禁用）。

        :param enabled: 为 True 时允许操作；为 False 时禁用操作。
        :return: 无返回值。
        """
        self.cardHost.setEnabled(enabled)
        self.termFilterComboBox.setEnabled(enabled)
        self.sortButton.setEnabled(enabled)
