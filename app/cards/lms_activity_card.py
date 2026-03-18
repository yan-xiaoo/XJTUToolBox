from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import CardWidget, IconWidget, BodyLabel, CaptionLabel, FluentIcon

from lms.models import ActivityType
from app.sub_interfaces.lms.common import time_text


class LMSActivityCard(CardWidget):
    """LMS 活动通用卡片。"""

    def __init__(self, activity: dict, parent=None):
        super().__init__(parent)

        self._activity = activity if isinstance(activity, dict) else {}
        self.activity_id = self._activity.get("id")
        self.activity_title = str(self._activity.get("title") or "-")
        self.activity_type = str(self._activity.get("type") or "")

        self.setFixedWidth(370)

        self.iconWidget = IconWidget(self._iconForType(self.activity_type), self)
        self.iconWidget.setFixedSize(30, 30)

        self.titleLabel = BodyLabel(self.activity_title, self)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setToolTip(self.activity_title)

        self.metaLabel = CaptionLabel(self._metaText(), self)
        self.metaLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(20, 14, 14, 14)
        self.hBoxLayout.setSpacing(14)
        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignVCenter)

        self.vBoxLayout = QVBoxLayout()
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(4)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.metaLabel)
        self.vBoxLayout.addStretch(1)

        self.hBoxLayout.addLayout(self.vBoxLayout, stretch=1)

    @staticmethod
    def _iconForType(activity_type: str):
        mapping = {
            ActivityType.HOMEWORK.value: FluentIcon.DICTIONARY,
            ActivityType.MATERIAL.value: FluentIcon.FOLDER,
            ActivityType.LESSON.value: FluentIcon.PLAY,
            ActivityType.LECTURE_LIVE.value: FluentIcon.RINGER,
        }
        return mapping.get(activity_type, FluentIcon.DOCUMENT)

    def _metaText(self) -> str:
        if self.activity_type == ActivityType.HOMEWORK.value:
            start = time_text(self._activity.get("start_time"))
            end = time_text(self._activity.get("end_time"))
            if start != "-" and end != "-":
                return self.tr("时间：{} ~ {}").format(start, end)
            if end != "-":
                return self.tr("截止：{}").format(end)
            if start != "-":
                return self.tr("开始：{}").format(start)
            return self.tr("时间：未知")

        created = time_text(self._activity.get("created_at"))
        return self.tr("创建时间：{}").format(created)
