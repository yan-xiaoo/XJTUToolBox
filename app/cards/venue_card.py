"""场馆卡片 - 仿照 LMSCourseCard 模式。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, pyqtProperty, QPropertyAnimation
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout

from qfluentwidgets import (ElevatedCardWidget, BodyLabel, CaptionLabel,
                            SubtitleLabel, IconWidget, FluentIcon, isDarkTheme)


class VenueCard(ElevatedCardWidget):
    """场馆卡片，带点击信号。"""

    venueClicked = pyqtSignal(object)  # venue_id（用 object 避免类型转换问题）

    def __init__(self, venue_id, name: str, address: str = "", parent=None):
        super().__init__(parent)
        self._venue_id = venue_id

        self.setFixedSize(370, 160)
        self.setBorderRadius(12)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)

        self.nameLabel = SubtitleLabel(name, self)
        self.nameLabel.setWordWrap(True)
        self.nameLabel.setToolTip(name)

        self.addressLabel = CaptionLabel(address or "-", self)
        self.addressLabel.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        self.addressLabel.setWordWrap(True)

        # 底部图标行（与 LMS 学分+人数行布局一致）
        self.bottomLayout = QHBoxLayout()

        self.iconWidget = IconWidget(FluentIcon.BASKETBALL, self)
        self.iconWidget.setFixedSize(14, 14)

        self.idLabel = CaptionLabel(f"ID: {venue_id}", self)

        self.bottomLayout.addWidget(self.iconWidget)
        self.bottomLayout.addWidget(self.idLabel)
        self.bottomLayout.addStretch(1)

        v.addWidget(self.nameLabel)
        v.addSpacing(4)
        v.addWidget(self.addressLabel)
        v.addStretch(1)
        v.addLayout(self.bottomLayout)

        for w in (self.nameLabel, self.addressLabel,
                  self.iconWidget, self.idLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        self.venueClicked.emit(self._venue_id)
        super().mouseReleaseEvent(event)


class VenueSkeletonCard(ElevatedCardWidget):
    """加载中的骨架卡片，仿照 CourseSkeletonCard。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(370, 160)
        self.setBorderRadius(12)

        self._pulse_opacity = 255
        self.pulse_anim = QPropertyAnimation(self, b"pulseOpacity", self)
        self.pulse_anim.setDuration(1200)
        self.pulse_anim.setStartValue(255)
        self.pulse_anim.setEndValue(100)
        self.pulse_anim.setLoopCount(-1)

        self.pulse_anim.valueChanged.connect(self._on_pulse_value_changed)
        self._ping_pong_forward = True

        try:
            from PyQt5.QtCore import QEasingCurve
            self.pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        except ImportError:
            pass

        self.pulse_anim.start()

    def _on_pulse_value_changed(self, value):
        if value == 100 and self._ping_pong_forward:
            self.pulse_anim.stop()
            self.pulse_anim.setStartValue(100)
            self.pulse_anim.setEndValue(255)
            self._ping_pong_forward = False
            self.pulse_anim.start()
        elif value == 255 and not self._ping_pong_forward:
            self.pulse_anim.stop()
            self.pulse_anim.setStartValue(255)
            self.pulse_anim.setEndValue(100)
            self._ping_pong_forward = True
            self.pulse_anim.start()

    def getPulseOpacity(self) -> int:
        return self._pulse_opacity

    def setPulseOpacity(self, opacity: int):
        self._pulse_opacity = opacity
        self.update()

    pulseOpacity = pyqtProperty(int, getPulseOpacity, setPulseOpacity)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        isDark = isDarkTheme()
        if isDark:
            bg_color = QColor(40, 40, 40)
            skeleton_color = QColor(60, 60, 60, self._pulse_opacity)
            border_color = QColor(255, 255, 255, 15)
        else:
            bg_color = QColor(255, 255, 255)
            skeleton_color = QColor(230, 230, 230, self._pulse_opacity)
            border_color = QColor(0, 0, 0, 15)

        rect = self.rect().adjusted(1, 1, -1, -1)
        r = self.borderRadius

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, r, r)

        painter.setPen(Qt.NoPen)
        painter.setBrush(skeleton_color)

        painter.drawRoundedRect(18, 20, 200, 26, 6, 6)
        painter.drawRoundedRect(18, 54, 120, 16, 4, 4)
        painter.drawRoundedRect(18, 102, 160, 16, 4, 4)
        painter.drawRoundedRect(18, 128, 40, 16, 4, 4)
        painter.drawRoundedRect(70, 128, 40, 16, 4, 4)
