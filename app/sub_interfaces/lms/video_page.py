from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtMultimedia import QMediaContent
from PyQt5.QtWidgets import QFrame, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, TitleLabel
from qfluentwidgets.multimedia import VideoWidget

from .common import format_replay_video_label, safe_text


class LMSVideoPage(QFrame):
    """思源学堂课程回放在线播放页面。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("videoPage")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 8, 12, 20)
        layout.setAlignment(Qt.AlignTop)

        self.videoTitleLabel = TitleLabel("-", self)
        self.videoTitleLabel.setWordWrap(True)
        self.videoTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.videoLabel = BodyLabel("-", self)
        self.videoLabel.setWordWrap(True)
        self.videoLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.videoHintLabel = CaptionLabel(self.tr("使用思源学堂回放链接在线播放当前视频"), self)
        self.videoHintLabel.setWordWrap(True)
        self.videoHintLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.videoHintLabel.setTextColor("#606060", "#d2d2d2")

        self.usageHintLabel = CaptionLabel(self.tr("将鼠标移出视频区域可以隐藏控制栏"), self)
        self.usageHintLabel.setWordWrap(True)
        self.usageHintLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.usageHintLabel.setTextColor("#606060", "#d2d2d2")

        self.videoWidget = VideoWidget(self)
        self.videoWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.videoWidget.setMinimumHeight(420)

        layout.addWidget(self.videoTitleLabel)
        layout.addWidget(self.videoLabel)
        layout.addWidget(self.videoHintLabel)
        layout.addWidget(self.usageHintLabel)
        layout.addWidget(self.videoWidget, stretch=1)

    def setReplayVideo(self, video_info: dict, activity_name: str) -> None:
        """用指定回放视频信息初始化播放器。"""
        label = format_replay_video_label(video_info.get("label"))
        play_url = str(video_info.get("download_url") or "").strip()

        self.videoTitleLabel.setText(safe_text(activity_name))
        if label == "-":
            self.videoLabel.setText(self.tr("当前视频：在线查看"))
        else:
            self.videoLabel.setText(self.tr("当前视频：{0}").format(label))

        self.stopPlayback()
        if play_url:
            self.videoWidget.setVideo(QUrl(play_url))
            self.videoWidget.play()

    def stopPlayback(self) -> None:
        """停止当前播放并清空媒体源。"""
        self.videoWidget.stop()
        self.videoWidget.player.setMedia(QMediaContent())

    def reset(self) -> None:
        """重置页面为默认状态。"""
        self.stopPlayback()
        self.videoTitleLabel.setText("-")
        self.videoLabel.setText("-")

    def hideEvent(self, event) -> None:
        """离开页面时立即停止播放。"""
        self.stopPlayback()
        super().hideEvent(event)
