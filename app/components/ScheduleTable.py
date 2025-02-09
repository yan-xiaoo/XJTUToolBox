from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGraphicsOpacityEffect, QLabel
from qfluentwidgets import StrongBodyLabel, BodyLabel, qconfig, getFont, isDarkTheme, Theme

from schedule.schedule_database import CourseInstance, CourseStatus


# 课程表表格中的每个元素
class ScheduleTableWidget(QWidget):
    LIGHT = "light"
    DARK = "dark"

    clicked = pyqtSignal(CourseInstance)

    COLOR_DICTION = {
        LIGHT: {
            CourseStatus.UNKNOWN: "#eaeaea",
            CourseStatus.CHECKED: "#def5e5",
            CourseStatus.NORMAL: "#ddffbc",
            CourseStatus.LEAVE: "#b5eaea",
            CourseStatus.LATE: "#ffeecc",
            CourseStatus.ABSENT: "#ffbcbc",
            CourseStatus.NO_CHECK: "#b7c4cf"
        },
        DARK: {
            CourseStatus.UNKNOWN: "#eaeaea",
            CourseStatus.CHECKED: "#def5e5",
            CourseStatus.NORMAL: "#ddffbc",
            CourseStatus.LEAVE: "#b5eaea",
            CourseStatus.LATE: "#ffeecc",
            CourseStatus.ABSENT: "#ffbcbc",
            CourseStatus.NO_CHECK: "#b7c4cf"
        }
    }

    def __init__(self, course: CourseInstance, parent=None):
        super().__init__(parent)

        self.course = course

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.nameLabel = StrongBodyLabel(course.name)
        self.placeLabel = BodyLabel(course.location)
        self.statusLabel = QLabel(self)
        font = getFont(13)
        font.setBold(True)
        self.statusLabel.setFont(font)
        self.setCourseStatus(course.status)

        # 设置不透明效果
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.set_opacity(1.0)  # 默认不透明

        self.statusLabel.setMinimumHeight(16)
        self.nameLabel.setMinimumHeight(15)
        # 设置字体居中显示
        self.statusLabel.setAlignment(self.statusLabel.alignment() | Qt.AlignCenter)
        # 设置自动换行
        self.placeLabel.setWordWrap(True)
        self.nameLabel.setWordWrap(True)

        self.nameLabel.setMinimumWidth(100)

        qconfig.themeChanged.connect(self.onThemeChanged)

        layout.addWidget(self.nameLabel)
        layout.addWidget(self.placeLabel)
        layout.addWidget(self.statusLabel)

    def set_opacity(self, opacity):
        """设置不透明度"""
        self.opacity_effect.setOpacity(opacity)

    # 增加悬浮时的效果
    def enterEvent(self, event):
        self.set_opacity(0.8)  # 降低不透明度
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_opacity(1.0)  # 恢复不透明度
        super().leaveEvent(event)

    def mouseReleaseEvent(self, a0):
        self.clicked.emit(self.course)

    @pyqtSlot(Theme)
    def onThemeChanged(self, _):
        self.setCourseStatus(self.course.status, False)

    def setCourseStatus(self, status: int | CourseStatus, save=True):
        """
        设置课程状态
        :param status: 课程状态
        :param save: 是否同样保存状态到数据库中
        """
        if isinstance(status, int):
            status = CourseStatus(status)
        if status == CourseStatus.UNKNOWN:
            self.statusLabel.setText("未知")
        elif status == CourseStatus.CHECKED:
            self.statusLabel.setText("已打卡")
        elif status == CourseStatus.NORMAL:
            self.statusLabel.setText("正常")
        elif status == CourseStatus.LEAVE:
            self.statusLabel.setText("请假")
        elif status == CourseStatus.LATE:
            self.statusLabel.setText("迟到")
        elif status == CourseStatus.ABSENT:
            self.statusLabel.setText("缺勤")
        elif status == CourseStatus.NO_CHECK:
            self.statusLabel.setText("无需考勤")
        else:
            self.statusLabel.setText("未知状态")
        self.statusLabel.setStyleSheet(self.getColoredStyleSheet(self.COLOR_DICTION[self.DARK if isDarkTheme() else self.LIGHT][status]))

        if save and self.course.status != status.value:
            self.course.status = status.value
            self.course.save()

    @staticmethod
    def getColoredStyleSheet(color: str) -> str:
        return f"color: {color}; background-color: #7e99a3;border-radius: 5px; padding: 2px 5px;"
