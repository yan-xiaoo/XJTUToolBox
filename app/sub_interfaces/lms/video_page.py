from __future__ import annotations

import os
import sys
from typing import Optional

from PyQt5.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QPropertyAnimation, QRectF, QSize, QSizeF, QUrl, Qt, pyqtSignal
from PyQt5.QtMultimedia import QMediaContent
from PyQt5.QtWidgets import QApplication, QDialog, QFrame, QGraphicsView, QShortcut, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import Action, BodyLabel, CaptionLabel, FluentIcon, RoundMenu, TitleLabel, TransparentDropDownPushButton
from qfluentwidgets.multimedia import MediaPlayBarButton, VideoWidget

from .common import format_replay_video_label, safe_text


class ReplayVideoWidget(VideoWidget):
    """沿用 BiliEmojiDD 的做法，将 Fluent 原播放条交给外层布局。

    参考：https://github.com/ldm0715/BiliEmojiDD/blob/main/app/components/video_player.py
    """

    fullScreenRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fullScreenMode = False
        self.timer.setSingleShot(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(Qt.black)
        self.viewport().setMouseTracking(True)
        self.playBar.installEventFilter(self)
        self.playBar.opacityAni.finished.connect(self._onControlsAnimationFinished)

    def setVideo(self, url):
        super().setVideo(url)
        # VideoItem 自己按比例缩放，避免 fitInView 再加边距、做第二次缩放。
        self.resetTransform()

    def hideEvent(self, event):
        # 不对已暂停或已结束的媒体再次 pause，避免后端改变其状态或位置。
        if self.player.isPlaying():
            self.pause()
        QGraphicsView.hideEvent(self, event)

    def setFullScreenMode(self, enabled):
        self.fullScreenMode = enabled
        self.videoItem.setAspectRatioMode(Qt.KeepAspectRatioByExpanding if enabled else Qt.KeepAspectRatio)
        self.resetTransform()
        if not enabled:
            self.timer.stop()
            self.playBar.opacityAni.stop()
            self.playBar.opacityEffect.setOpacity(1)
            self.playBar.show()

    def sizeHint(self):
        return QSize(240, 180)

    def minimumSizeHint(self):
        return QSize(160, 90)

    def resizeEvent(self, event):
        QGraphicsView.resizeEvent(self, event)
        self.videoItem.setSize(QSizeF(self.viewport().size()))
        self.graphicsScene.setSceneRect(QRectF(0, 0, self.viewport().width(), self.viewport().height()))
        if self.fullScreenMode:
            self.playBar.setGeometry(11, self.height() - self.playBar.height() - 11,
                                     max(100, self.width() - 22), self.playBar.height())

    def showControls(self):
        if self.fullScreenMode:
            if self.playBar.isHidden():
                self.playBar.opacityAni.stop()
                self.playBar.opacityEffect.setOpacity(0)
                self.playBar.show()
            animation = self.playBar.opacityAni
            fadingIn = animation.state() == QAbstractAnimation.Running and animation.endValue() == 1
            fadingOut = animation.state() == QAbstractAnimation.Running and animation.endValue() == 0
            # 淡出首帧前透明度仍为 1，也需要立即响应显示请求。
            if not fadingIn and (self.playBar.opacityEffect.opacity() < 1 or fadingOut):
                animation.stop()
                self.playBar.fadeIn()
            self.playBar.raise_()
            self.timer.start(3000)

    def eventFilter(self, obj, event):
        if obj is self.playBar and event.type() == QEvent.Enter:
            self.showControls()
        return super().eventFilter(obj, event)

    def _onControlsAnimationFinished(self):
        if self.fullScreenMode and self.playBar.opacityEffect.opacity() == 0:
            self.playBar.hide()

    def enterEvent(self, event):
        QGraphicsView.enterEvent(self, event)
        self.showControls()

    def leaveEvent(self, event):
        QGraphicsView.leaveEvent(self, event)

    def mouseMoveEvent(self, event):
        self.showControls()
        QGraphicsView.mouseMoveEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.fullScreenRequested.emit()

    def _onHideTimeOut(self):
        if not self.fullScreenMode:
            return
        if self.playBar.underMouse() or QApplication.activePopupWidget() or self.playBar.volumeButton.volumeFlyout.isVisible():
            self.timer.start(3000)
        else:
            self.playBar.opacityAni.stop()
            self.playBar.fadeOut()


class _PlayerDialog(QDialog):
    """关闭前记录播放状态，避免 hideEvent 自动暂停后丢失原状态。"""

    def __init__(self, view, parent):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        # 显式定位，避免 QDialog 首次显示时按父窗口居中，偏离完整屏幕区域。
        self.setGeometry(parent.screen().geometry())
        self.view = view
        self.wasPlaying = view.player.isPlaying()
        self._closingResult = None
        self.transitionAnimation = QPropertyAnimation(self, b"windowOpacity", self)
        self.transitionAnimation.setDuration(360)
        self.transitionAnimation.setEasingCurve(QEasingCurve.InOutCubic)
        self.transitionAnimation.finished.connect(self._finishTransition)
        self.setWindowOpacity(0)

    def showEvent(self, event):
        super().showEvent(event)
        self.transitionAnimation.setStartValue(0)
        self.transitionAnimation.setEndValue(1)
        self.transitionAnimation.start()

    def done(self, result):
        if self._closingResult is not None:
            return
        self._closingResult = result
        self.transitionAnimation.stop()
        self.transitionAnimation.setStartValue(self.windowOpacity())
        self.transitionAnimation.setEndValue(0)
        self.transitionAnimation.start()

    def _finishTransition(self):
        if self._closingResult is not None:
            # 淡出期间可能已播放结束；在真正隐藏触发 pause 前读取最新状态。
            self.wasPlaying = self.view.player.isPlaying()
            QDialog.done(self, self._closingResult)

    def closeImmediately(self):
        self.wasPlaying = self.view.player.isPlaying()
        self.transitionAnimation.stop()
        QDialog.done(self, QDialog.Rejected)


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

        self.usageHintLabel = CaptionLabel(self.tr("双击画面或按 F11 全屏，Esc 返回；全屏时控制栏自动隐藏"), self)
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
        self.fullScreenDialog = None

        self.speedButton = TransparentDropDownPushButton("1×", self.playBar)
        self.speedMenu = RoundMenu(parent=self.speedButton)
        for rate in (0.5, 0.75, 1, 1.25, 1.5, 2):
            action = Action(f"{rate:g}×", self.speedMenu)
            action.triggered.connect(lambda checked=False, r=rate: self.videoWidget.player.setPlaybackRate(r))
            self.speedMenu.addAction(action)
        self.speedButton.setMenu(self.speedMenu)
        self.videoWidget.player.playbackRateChanged.connect(lambda r: self.speedButton.setText(f"{r:g}×"))
        self.fullScreenButton = MediaPlayBarButton(FluentIcon.FULL_SCREEN, self.playBar)
        self.fullScreenButton.setToolTip(self.tr("全屏（F11）"))
        self.fullScreenButton.clicked.connect(self.toggleFullScreen)
        self.playBar.rightButtonLayout.addWidget(self.speedButton)
        self.playBar.rightButtonLayout.addWidget(self.fullScreenButton)
        self.videoWidget.player.stateChanged.connect(lambda _: self.playBar.playButton.setPlay(self.videoWidget.player.isPlaying()))
        self.videoWidget.fullScreenRequested.connect(self.toggleFullScreen)
        QShortcut("F11", self.playerContainer, activated=self.toggleFullScreen)
        QShortcut("Escape", self.playerContainer, activated=lambda: self.fullScreenDialog.reject() if self.fullScreenDialog else None)

        layout.addWidget(self.videoTitleLabel)
        layout.addWidget(self.videoLabel)
        layout.addWidget(self.videoHintLabel)
        layout.addWidget(self.usageHintLabel)
        layout.addWidget(self.playerContainer, stretch=1)

    def _onPositionChanged(self, position):
        # WMF 在尚未取得有效位置时可能发出 qint64 的未知值，不能传给 32 位滑块。
        if 0 <= position <= min(2**31 - 1, max(0, self.videoWidget.player.duration())):
            self.playBar._onPositionChanged(position)

    def toggleFullScreen(self):
        if self.fullScreenDialog:
            self.fullScreenDialog.reject()
            return
        playing = self.videoWidget.player.isPlaying()
        self.fullScreenDialog = _PlayerDialog(self.videoWidget, self.window())
        self.fullScreenDialog.setWindowTitle(self.videoTitleLabel.text())
        dialogLayout = QVBoxLayout(self.fullScreenDialog)
        dialogLayout.setContentsMargins(0, 0, 0, 0)
        dialogLayout.addWidget(self.playerContainer)
        self.playerLayout.removeWidget(self.playBar)
        self.playBar.setParent(self.videoWidget)
        self.videoWidget.setFullScreenMode(True)
        self.fullScreenButton.setIcon(FluentIcon.BACK_TO_WINDOW)
        self.fullScreenButton.setToolTip(self.tr("退出全屏（Esc）"))
        self.fullScreenDialog.finished.connect(self._restorePlayer)
        self.fullScreenDialog.showFullScreen()
        self.fullScreenDialog.raise_()
        self.fullScreenDialog.activateWindow()
        self.videoWidget.showControls()
        if playing:
            self.videoWidget.play()

    def _restorePlayer(self):
        dialog = self.fullScreenDialog
        self.fullScreenDialog = None
        self.videoWidget.setFullScreenMode(False)
        self.layout().addWidget(self.playerContainer, stretch=1)
        self.playerLayout.addWidget(self.playBar)
        self.playerContainer.show()
        self.playBar.show()
        self.fullScreenButton.setIcon(FluentIcon.FULL_SCREEN)
        self.fullScreenButton.setToolTip(self.tr("全屏（F11）"))
        if dialog.wasPlaying:
            self.videoWidget.play()
        dialog.deleteLater()

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
        if self.fullScreenDialog:
            self.fullScreenDialog.closeImmediately()

    def reset(self) -> None:
        """重置页面为默认状态。"""
        self.stopPlayback()
        self.videoTitleLabel.setText("-")
        self.videoLabel.setText("-")

    def hideEvent(self, event) -> None:
        """离开页面时立即停止播放。"""
        self.stopPlayback()
        super().hideEvent(event)
