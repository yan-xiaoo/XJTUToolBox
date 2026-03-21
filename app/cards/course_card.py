import random

from PyQt5.QtCore import Qt, pyqtSignal, pyqtProperty, QPropertyAnimation, QRectF
from PyQt5.QtGui import QColor, QPainter, QImage, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout

from qfluentwidgets import ElevatedCardWidget, SubtitleLabel, CaptionLabel, IconWidget, FluentIcon, isDarkTheme, \
    BodyLabel


class LMSCourseCard(ElevatedCardWidget):
    """LMS Course Card with pseudo-glassmorphism."""
    def __init__(self, course: dict, parent=None):
        super().__init__(parent)
        self.course_id = course.get("id")
        self.course_id = self.course_id if isinstance(self.course_id, int) else -1
        self.course_name = str(course.get("name") or "-")

        self.setFixedWidth(370)
        self.setMinimumHeight(160)
        self.setMaximumHeight(160)
        self.setBorderRadius(12)

        self.verticalLayout = QVBoxLayout(self)
        self.verticalLayout.setContentsMargins(18, 16, 18, 16)

        # Course Name
        self.nameLabel = SubtitleLabel(self.course_name, self)
        self.nameLabel.setWordWrap(True)
        self.nameLabel.setToolTip(self.course_name)

        # Academic Year/Semester
        semester = course.get("semester", {}) if isinstance(course.get("semester"), dict) else {}
        academic_year = course.get("academic_year", {}) if isinstance(course.get("academic_year"), dict) else {}

        # semester['code'] 可能的格式为 "2023-1" 或 "2023-2"，分别代表上半年和下半年
        try:
            year, term = semester["code"].split("-")
            term_string = f"{int(year)}-{int(year) + 1}-{int(term)}"
        except (ValueError, KeyError):
            # academic_year.get("name") 可能的格式为 "2023-2024"，我们可以直接使用它
            term_string = academic_year.get("name", "-")

        self.termLabel = CaptionLabel(term_string.strip(), self)
        self.termLabel.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))

        # Instructors
        instructors = course.get("instructors", []) if isinstance(course.get("instructors"), list) else []
        instructor_text = "、".join(str(one.get("name", "")) for one in instructors if isinstance(one, dict) and one.get("name"))
        self.instructorLabel = BodyLabel(instructor_text or "-", self)
        self.instructorLabel.setWordWrap(False)

        # Credit & Student Count
        self.hBoxLayout = QHBoxLayout()
        course_attr = course.get("course_attributes", {}) if isinstance(course.get("course_attributes"), dict) else {}

        self.creditIcon = IconWidget(FluentIcon.EDUCATION, self)
        self.creditIcon.setFixedSize(14, 14)
        self.creditLabel = CaptionLabel(str(course.get("credit") or "-"), self)

        self.studentIcon = IconWidget(FluentIcon.PEOPLE, self)
        self.studentIcon.setFixedSize(14, 14)
        self.studentLabel = CaptionLabel(str(course_attr.get("student_count") or "-"), self)

        self.hBoxLayout.addWidget(self.creditIcon)
        self.hBoxLayout.addWidget(self.creditLabel)
        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self.studentIcon)
        self.hBoxLayout.addWidget(self.studentLabel)
        self.hBoxLayout.addStretch(1)

        self.verticalLayout.addWidget(self.nameLabel)
        self.verticalLayout.addWidget(self.termLabel)
        self.verticalLayout.addWidget(self.instructorLabel)
        self.verticalLayout.addLayout(self.hBoxLayout)

        for widget in (
            self.nameLabel,
            self.termLabel,
            self.instructorLabel,
            self.creditIcon,
            self.creditLabel,
            self.studentIcon,
            self.studentLabel,
        ):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.setCursor(Qt.PointingHandCursor)


class CourseSkeletonCard(ElevatedCardWidget):
    """Skeleton loading card for courses."""
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
        
        # Ping-pong loop
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
