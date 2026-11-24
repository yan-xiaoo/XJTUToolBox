from __future__ import annotations

import os
import sys
from typing import Optional

from PyQt5.QtCore import QRectF, QSize, QSizeF, QUrl, Qt
from PyQt5.QtMultimedia import QMediaContent
from PyQt5.QtWidgets import QFrame, QGraphicsView, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, TitleLabel
from qfluentwidgets.multimedia import VideoWidget

from .common import format_replay_video_label, safe_text


class ReplayVideoWidget(VideoWidget):
    """沿用 BiliEmojiDD 的做法，将 Fluent 原播放条交给外层布局。

    参考：https://github.com/ldm0715/BiliEmojiDD/blob/main/app/components/video_player.py
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(Qt.black)

    def setVideo(self, url):
        super().setVideo(url)
        # VideoItem 自己按比例缩放，避免 fitInView 再加边距、做第二次缩放。
        self.resetTransform()


    def sizeHint(self):
        return QSize(240, 180)

    def minimumSizeHint(self):
        return QSize(160, 90)

    def resizeEvent(self, event):
        QGraphicsView.resizeEvent(self, event)
        self.videoItem.setSize(QSizeF(self.viewport().size()))
        self.graphicsScene.setSceneRect(QRectF(0, 0, self.viewport().width(), self.viewport().height()))


    def enterEvent(self, event):
        QGraphicsView.enterEvent(self, event)

    def leaveEvent(self, event):
        QGraphicsView.leaveEvent(self, event)


    def _onHideTimeOut(self):
        return


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

        self.usageHintLabel = CaptionLabel(self.tr("使用画面下方控制栏进行播放操作"), self)
        self.usageHintLabel.setWordWrap(True)
        self.usageHintLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.usageHintLabel.setTextColor("#606060", "#d2d2d2")

        # DirectShow 依赖额外的 MP4 过滤器；Windows 优先使用 Qt 自带的 WMF 后端。
        if sys.platform == "win32":
            os.environ.setdefault("QT_MULTIMEDIA_PREFERRED_PLUGINS", "windowsmediafoundation")
        self.playerContainer = QWidget(self)
        self.playerLayout = QVBoxLayout(self.playerContainer)
        self.playerLayout.setContentsMargins(0, 0, 0, 0)
        self.playerLayout.setSpacing(6)
        self.videoWidget = ReplayVideoWidget(self.playerContainer)
        self.videoWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.videoWidget.setMinimumSize(160, 90)
        self.playBar = self.videoWidget.playBar
        self.videoWidget.player.positionChanged.disconnect(self.playBar._onPositionChanged)
        self.videoWidget.player.positionChanged.connect(self._onPositionChanged)
        self.playerLayout.addWidget(self.videoWidget, 1)
        self.playerLayout.addWidget(self.playBar)
        self.videoWidget.player.stateChanged.connect(lambda _: self.playBar.playButton.setPlay(self.videoWidget.player.isPlaying()))

        layout.addWidget(self.videoTitleLabel)
        layout.addWidget(self.videoLabel)
        layout.addWidget(self.videoHintLabel)
        layout.addWidget(self.usageHintLabel)
        layout.addWidget(self.playerContainer, stretch=1)

    def _onPositionChanged(self, position):
        # WMF 在尚未取得有效位置时可能发出 qint64 的未知值，不能传给 32 位滑块。
        if 0 <= position <= min(2**31 - 1, max(0, self.videoWidget.player.duration())):
            self.playBar._onPositionChanged(position)

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
