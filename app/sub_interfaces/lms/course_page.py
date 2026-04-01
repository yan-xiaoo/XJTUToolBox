import re

from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QTimer
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
        self._enter_animations: list[QParallelAnimationGroup] = []

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
        self.flowLayout = FlowLayout(self.cardHost, needAni=False)
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
        self._rebuildFilterItems(preserve_current=False)
        self._applyCurrentFilter()

    def upsertCourses(self, courses: list[dict]):
        """
        更新已经存在的课程列表，插入一些新的课程。

        :param courses: 新增的课程。其中已经存在的课程会被忽略，而不存在的课程会被插入到课程列表中。
        """
        updates = [one for one in courses if isinstance(one, dict)]
        if not updates:
            return

        index_by_id: dict[int, int] = {}
        for index, course in enumerate(self._all_courses):
            course_id = course.get("id") if isinstance(course, dict) else None
            if isinstance(course_id, int):
                index_by_id[course_id] = index

        changed = False
        for course in updates:
            course_id = course.get("id")
            if not isinstance(course_id, int):
                continue
            old_index = index_by_id.get(course_id)
            if old_index is None:
                self._all_courses.append(course)
                index_by_id[course_id] = len(self._all_courses) - 1
            else:
                self._all_courses[old_index] = course
            changed = True

        if not changed:
            return

        self._rebuildFilterItems(preserve_current=True)
        self._applyCurrentFilter()

    def getCoursesSnapshot(self) -> list[dict]:
        """
        列出当前页面全部的课程（不使用页面设置筛选）
        """
        return [one for one in self._all_courses if isinstance(one, dict)]

    def _clearCourseCards(self):
        """仅清除课程卡片，不影响原始数据与筛选项。"""
        for animation in self._enter_animations:
            animation.stop()
        self._enter_animations.clear()

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

        self._animateCourseCardsIn()

    def _animateCourseCardsIn(self):
        """
        播放课程卡片出现的动画
        """
        self._enter_animations.clear()
        if not self._course_cards:
            return

        self.flowLayout.activate()
        ordered_cards = sorted(self._course_cards, key=lambda one: (one.y(), one.x()))
        row_tolerance = 12
        rows: list[list] = []
        for card in ordered_cards:
            if not rows or abs(card.y() - rows[-1][0].y()) > row_tolerance:
                rows.append([card])
            else:
                rows[-1].append(card)
        for row in rows:
            row.sort(key=lambda one: one.x())

        animation_duration = 360
        within_row_step = 70
        between_row_gap = 30
        row_start_delay = 0

        for row in rows:
            for col_index, card in enumerate(row):
                delay = row_start_delay + col_index * within_row_step
                card.setMinimumHeight(0)
                card.setMaximumHeight(0)
                card.updateGeometry()

                min_height_animation = QPropertyAnimation(card, b"minimumHeight", card)
                min_height_animation.setDuration(animation_duration)
                min_height_animation.setStartValue(0)
                min_height_animation.setEndValue(160)
                min_height_animation.setEasingCurve(QEasingCurve.OutBack)

                max_height_animation = QPropertyAnimation(card, b"maximumHeight", card)
                max_height_animation.setDuration(animation_duration)
                max_height_animation.setStartValue(0)
                max_height_animation.setEndValue(160)
                max_height_animation.setEasingCurve(QEasingCurve.OutBack)

                group = QParallelAnimationGroup(self)
                group.addAnimation(min_height_animation)
                group.addAnimation(max_height_animation)

                def finalize(target=card):
                    try:
                        target.setMinimumHeight(160)
                        target.setMaximumHeight(160)
                        target.updateGeometry()
                    except RuntimeError:
                        return

                group.finished.connect(finalize)
                self._enter_animations.append(group)
                QTimer.singleShot(delay, group.start)

            row_anim_span = (len(row) - 1) * within_row_step + animation_duration
            row_start_delay += row_anim_span + between_row_gap

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

    def _rebuildFilterItems(self, preserve_current: bool = False):
        """
        重建筛选框选项，仅包含有课程的学年-学期。

        :param preserve_current: 是否尝试保留当前选中的筛选项（如果仍然存在）。默认为 False。
        """
        current_key = self.termFilterComboBox.currentData() if preserve_current else self._FILTER_ALL_KEY
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
        selected_index = self.termFilterComboBox.findData(current_key)
        self.termFilterComboBox.setCurrentIndex(selected_index if selected_index >= 0 else 0)
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
