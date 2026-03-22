from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QActionGroup, QFrame, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from qfluentwidgets import Action, BodyLabel, CheckableMenu, FlowLayout, FluentIcon, MenuIndicatorType, Pivot, \
    TransparentDropDownPushButton

from lms.models import ActivityType
from app.cards.lms_activity_card import LMSActivityCard
from .common import PageStatus, create_loading_frame, create_retry_frame


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
        self._activity_cards: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.topBar = QFrame(self)
        self.topBarLayout = QHBoxLayout(self.topBar)
        self.topBarLayout.setContentsMargins(0, 0, 0, 0)
        self.topBarLayout.setSpacing(12)

        self.activityTypePivot = Pivot(self)
        self.activityTypePivot.addItem(ActivityType.HOMEWORK.value, self.tr("作业"), onClick=lambda: self._onActivityTypeChanged(ActivityType.HOMEWORK.value))
        self.activityTypePivot.addItem(ActivityType.MATERIAL.value, self.tr("资料"), onClick=lambda: self._onActivityTypeChanged(ActivityType.MATERIAL.value))
        self.activityTypePivot.addItem(ActivityType.LESSON.value, self.tr("课程回放"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LESSON.value))
        self.activityTypePivot.addItem(ActivityType.LECTURE_LIVE.value, self.tr("直播"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LECTURE_LIVE.value))
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)

        self.sortButton = TransparentDropDownPushButton(FluentIcon.SYNC, self.tr("排序方式"), self.topBar)
        self.sortButton.setFixedHeight(34)
        self.sortButton.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sortButton.setVisible(False)

        self.lessonSortGroup = QActionGroup(self)
        self.lessonTimeAscAction = Action(FluentIcon.UP, self.tr("时间 前→后"), self, checkable=True)
        self.lessonTimeDescAction = Action(FluentIcon.DOWN, self.tr("时间 后→前"), self, checkable=True)
        self.lessonSortGroup.addAction(self.lessonTimeAscAction)
        self.lessonSortGroup.addAction(self.lessonTimeDescAction)
        self.lessonTimeDescAction.setChecked(True)

        self.lessonTimeAscAction.triggered.connect(self._onSortChanged)
        self.lessonTimeDescAction.triggered.connect(self._onSortChanged)

        self.sortMenu = CheckableMenu(parent=self, indicatorType=MenuIndicatorType.RADIO)
        self.sortMenu.addActions([self.lessonTimeAscAction, self.lessonTimeDescAction])
        self.sortButton.setMenu(self.sortMenu)

        self.topBarLayout.addWidget(self.activityTypePivot, stretch=1)

        self.cardHost = QWidget(self)
        self.flowLayout = FlowLayout(self.cardHost, needAni=False)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setVerticalSpacing(16)
        self.flowLayout.setHorizontalSpacing(16)

        self.loadingFrame = create_loading_frame(self)
        self.loadingFrame.setVisible(False)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

        layout.addWidget(self.topBar)
        layout.addWidget(self.sortButton, alignment=Qt.AlignHCenter)
        layout.addWidget(self.cardHost)
        layout.addWidget(self.loadingFrame)
        layout.addWidget(self.failFrame)

    def setPageStatus(self, status: PageStatus):
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            self.loadingFrame.setVisible(True)
            self.cardHost.setVisible(False)
            self.failFrame.setVisible(False)
            return
        if status == PageStatus.ERROR:
            self.loadingFrame.setVisible(False)
            self.cardHost.setVisible(False)
            self.failFrame.setVisible(True)
            return

        self.loadingFrame.setVisible(False)
        self.cardHost.setVisible(True)
        self.failFrame.setVisible(False)

    def setActivities(self, activities: list[dict]):
        """写入活动全集并按当前类型刷新表格。

        :param activities: 活动列表，每项为活动字典。
        :return: 无返回值。
        """
        self._activities = activities if isinstance(activities, list) else []
        self.filterActivities(self.activity_type_filter)

    def upsertActivities(self, activities: list[dict]):
        updates = [one for one in activities if isinstance(one, dict)]
        if not updates:
            return

        index_by_id: dict[int, int] = {}
        for index, activity in enumerate(self._activities):
            activity_id = activity.get("id") if isinstance(activity, dict) else None
            if isinstance(activity_id, int):
                index_by_id[activity_id] = index

        changed = False
        for activity in updates:
            activity_id = activity.get("id")
            if not isinstance(activity_id, int):
                continue
            old_index = index_by_id.get(activity_id)
            if old_index is None:
                self._activities.append(activity)
                index_by_id[activity_id] = len(self._activities) - 1
            else:
                self._activities[old_index] = activity
            changed = True

        if not changed:
            return

        self.filterActivities(self.activity_type_filter)

    def getActivitiesSnapshot(self) -> list[dict]:
        return [one for one in self._activities if isinstance(one, dict)]

    def filterActivities(self, key: str):
        """按活动类型过滤并重绘表格。

        :param key: 活动类型键（如 homework/material/lesson/lecture_live）。
        :return: 无返回值。
        """
        filtered = [one for one in self._activities if str(one.get("type") or "") == key]
        self._filtered_activities = self._sortActivities(filtered, key)
        self._updateSortButtonVisibility(key)
        self._rebuildActivityCards()

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
        self._clearActivityCards()
        self._updateSortButtonVisibility(self.activity_type_filter)

    def reset(self):
        """重置活动页到默认状态（默认类型为作业）。

        :return: 无返回值。
        """
        self.activity_type_filter = ActivityType.HOMEWORK.value
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)
        self.lessonTimeDescAction.setChecked(True)
        self.clearData()
        self.setPageStatus(PageStatus.NORMAL)

    def setInteractionEnabled(self, enabled: bool):
        """设置活动表格是否可交互。

        :param enabled: 为 True 时允许点击活动；为 False 时禁用表格操作。
        :return: 无返回值。
        """
        self.cardHost.setEnabled(enabled)

    def _onActivityTypeChanged(self, key: str):
        """处理 Pivot 类型切换并发出类型变化信号。"""
        self.activity_type_filter = key
        self.filterActivities(key)
        self.activityTypeChanged.emit(key)

    def _onSortChanged(self):
        """处理课程回放排序方式切换。"""
        self.filterActivities(self.activity_type_filter)

    def _updateSortButtonVisibility(self, key: str):
        """仅在课程回放分类下显示排序按钮。"""
        self.sortButton.setVisible(key == ActivityType.LESSON.value)

    def _sortActivities(self, activities: list[dict], key: str) -> list[dict]:
        """按当前筛选类型返回排序后的活动列表。"""
        if key != ActivityType.LESSON.value:
            return list(activities)

        valid_items: list[tuple[datetime, dict]] = []
        invalid_items: list[dict] = []
        for activity in activities:
            sort_time = self._activitySortTime(activity)
            if sort_time is None:
                invalid_items.append(activity)
                continue
            valid_items.append((sort_time, activity))

        valid_items.sort(key=lambda item: item[0], reverse=self.lessonTimeDescAction.isChecked())
        return [activity for _, activity in valid_items] + invalid_items

    @staticmethod
    def _activitySortTime(activity: dict) -> datetime | None:
        """提取活动排序使用的时间字段。"""
        for value in (activity.get("start_time"), activity.get("created_at"), activity.get("updated_at")):
            if not isinstance(value, str) or not value:
                continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        return None

    def _clearActivityCards(self):
        """清理已渲染的活动卡片。"""
        for card in self._activity_cards:
            self.flowLayout.removeWidget(card)
            card.deleteLater()
        self._activity_cards.clear()

    def _rebuildActivityCards(self):
        """根据当前过滤结果重建活动卡片。"""
        self._clearActivityCards()

        # 在没有活动时，显示一个简单的提示
        if not self._filtered_activities:
            label = BodyLabel(self.tr("当前分类下暂无内容"), self.cardHost)
            # 将这个 label 加到 activity_card 中，这样就可以跟随活动切换而消失了
            self.flowLayout.addWidget(label)
            self._activity_cards.append(label)

        for activity in self._filtered_activities:
            card = LMSActivityCard(activity, self.cardHost)
            card.clicked.connect(lambda _=False, one=activity: self._onActivityClicked(one))
            self.flowLayout.addWidget(card)
            self._activity_cards.append(card)

        self.cardHost.adjustSize()

    def _onActivityClicked(self, activity: dict):
        """处理活动点击事件并发出活动选择信号。"""
        if not isinstance(activity, dict):
            return
        activity_id = activity.get("id")
        if not isinstance(activity_id, int):
            return
        self.activitySelected.emit(activity_id, str(activity.get("title") or "-"))
