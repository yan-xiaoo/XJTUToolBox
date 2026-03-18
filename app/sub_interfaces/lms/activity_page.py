from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget
from qfluentwidgets import Pivot, FlowLayout, BodyLabel

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

        self.activityTypePivot = Pivot(self)
        self.activityTypePivot.addItem(ActivityType.HOMEWORK.value, self.tr("作业"), onClick=lambda: self._onActivityTypeChanged(ActivityType.HOMEWORK.value))
        self.activityTypePivot.addItem(ActivityType.MATERIAL.value, self.tr("资料"), onClick=lambda: self._onActivityTypeChanged(ActivityType.MATERIAL.value))
        self.activityTypePivot.addItem(ActivityType.LESSON.value, self.tr("课程回放"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LESSON.value))
        self.activityTypePivot.addItem(ActivityType.LECTURE_LIVE.value, self.tr("直播"), onClick=lambda: self._onActivityTypeChanged(ActivityType.LECTURE_LIVE.value))
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)

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

        layout.addWidget(self.activityTypePivot)
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

    def filterActivities(self, key: str):
        """按活动类型过滤并重绘表格。

        :param key: 活动类型键（如 homework/material/lesson/lecture_live）。
        :return: 无返回值。
        """
        self._filtered_activities = [one for one in self._activities if str(one.get("type") or "") == key]
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
        self.cardHost.setEnabled(enabled)

    def _onActivityTypeChanged(self, key: str):
        """处理 Pivot 类型切换并发出类型变化信号。"""
        self.activity_type_filter = key
        self.filterActivities(key)
        self.activityTypeChanged.emit(key)

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
