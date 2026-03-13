from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QSizePolicy, QTableWidgetItem
from qfluentwidgets import Pivot, TableWidget

from lms.models import ActivityType
from .common import PageStatus, create_loading_frame, create_retry_frame, apply_full_width_column_width, update_table_height, bool_text, time_text, activity_status_text


class LMSActivityPage(QFrame):
    # 用户点击活动行后，通知主容器当前选择的活动 ID 与活动标题。
    activitySelected = pyqtSignal(int, str)
    # 活动类型筛选发生变化时通知主容器。
    activityTypeChanged = pyqtSignal(str)
    # 用户点击重试按钮后，请求主容器重新加载活动。
    retryRequested = pyqtSignal()

    def __init__(self, parent=None):
        """初始化活动页组件与筛选器。"""
        super().__init__(parent)
        self.setObjectName("activityPage")
        self.activity_type_filter = ActivityType.HOMEWORK.value
        self._activities: list[dict] = []
        self._filtered_activities: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.activityTypePivot = Pivot(self)
        self.activityTypePivot.addItem(ActivityType.HOMEWORK.value, self.tr("作业"), onClick=lambda: self._onActivityTypeChanged(ActivityType.HOMEWORK.value))
        self.activityTypePivot.addItem(ActivityType.MATERIAL.value, self.tr("资料"), onClick=lambda: self._onActivityTypeChanged(ActivityType.MATERIAL.value))
        self.activityTypePivot.addItem(ActivityType.LESSON.value, self.tr("课程回放"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LESSON.value))
        self.activityTypePivot.addItem(ActivityType.LECTURE_LIVE.value, self.tr("直播"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LECTURE_LIVE.value))
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)

        self.activityTable = TableWidget(self)
        self.activityTable.setRowCount(0)
        self.activityTable.setColumnCount(5)
        self.activityTable.setHorizontalHeaderLabels([
            self.tr("活动"), self.tr("开始时间"), self.tr("结束时间"), self.tr("发布"), self.tr("状态")
        ])
        apply_full_width_column_width(self.activityTable)
        self.activityTable.verticalHeader().setVisible(False)
        self.activityTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.activityTable.setMinimumHeight(0)
        self.activityTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.activityTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.activityTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.activityTable.cellClicked.connect(self._onActivityClicked)

        self.loadingFrame = create_loading_frame(self)
        self.loadingFrame.setVisible(False)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

        layout.addWidget(self.activityTypePivot)
        layout.addWidget(self.activityTable)
        layout.addWidget(self.loadingFrame)
        layout.addWidget(self.failFrame)

        update_table_height(self.activityTable, min_rows=1, min_height=140)

    def setPageStatus(self, status: PageStatus):
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            self.loadingFrame.setVisible(True)
            self.activityTable.setVisible(False)
            self.failFrame.setVisible(False)
            return
        if status == PageStatus.ERROR:
            self.loadingFrame.setVisible(False)
            self.activityTable.setVisible(False)
            self.failFrame.setVisible(True)
            return

        self.loadingFrame.setVisible(False)
        self.activityTable.setVisible(True)
        self.failFrame.setVisible(False)

    def setActivities(self, activities: list[dict]):
        """写入活动全集并按当前类型刷新表格。

        :param activities: 活动列表，每项为活动字典。
        :return: 无返回值。
        """
        self._activities = activities if isinstance(activities, list) else []
        self.filterActivities(self.activity_type_filter)

    def filterActivities(self, key: str):
        """按活动类型过滤并重绘表格。

        :param key: 活动类型键（如 homework/material/lesson/lecture_live）。
        :return: 无返回值。
        """
        self._filtered_activities = [one for one in self._activities if str(one.get("type") or "") == key]
        self.activityTable.setRowCount(len(self._filtered_activities))

        for row, activity in enumerate(self._filtered_activities):
            self.activityTable.setItem(row, 0, QTableWidgetItem(str(activity.get("title") or "-")))
            self.activityTable.setItem(row, 1, QTableWidgetItem(time_text(activity.get("start_time"))))
            self.activityTable.setItem(row, 2, QTableWidgetItem(time_text(activity.get("end_time"))))
            self.activityTable.setItem(row, 3, QTableWidgetItem(bool_text(activity.get("published"))))
            self.activityTable.setItem(row, 4, QTableWidgetItem(activity_status_text(activity)))

        self.activityTable.resizeRowsToContents()
        update_table_height(self.activityTable, min_rows=1, min_height=140)

    def setCurrentActivityType(self, key: str):
        """设置当前活动类型并同步筛选视图。

        :param key: 目标活动类型键。
        :return: 无返回值。
        """
        self.activity_type_filter = key
        self.activityTypePivot.setCurrentItem(key)
        self.filterActivities(key)

    def clearData(self):
        """清空活动数据与表格内容。

        :return: 无返回值。
        """
        self._activities = []
        self._filtered_activities = []
        self.activityTable.setRowCount(0)
        update_table_height(self.activityTable, min_rows=1, min_height=140)

    def reset(self):
        """重置活动页到默认状态（默认类型为作业）。

        :return: 无返回值。
        """
        self.activity_type_filter = ActivityType.HOMEWORK.value
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)
        self.clearData()
        self.setPageStatus(PageStatus.NORMAL)

    def setInteractionEnabled(self, enabled: bool):
        """设置活动表格是否可交互。

        :param enabled: 为 True 时允许点击活动；为 False 时禁用表格操作。
        :return: 无返回值。
        """
        self.activityTable.setEnabled(enabled)

    def _onActivityTypeChanged(self, key: str):
        """处理 Pivot 类型切换并发出类型变化信号。"""
        self.activity_type_filter = key
        self.filterActivities(key)
        self.activityTypeChanged.emit(key)

    def _onActivityClicked(self, row: int, _column: int):
        """处理活动点击事件并发出活动选择信号。"""
        if row < 0 or row >= len(self._filtered_activities):
            return
        activity = self._filtered_activities[row]
        activity_id = activity.get("id")
        if not isinstance(activity_id, int):
            return
        self.activitySelected.emit(activity_id, str(activity.get("title") or "-"))
