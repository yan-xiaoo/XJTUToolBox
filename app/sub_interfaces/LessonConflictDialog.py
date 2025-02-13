# 用于处理新获得的课程和原先课程冲突的对话框
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtWidgets import QHBoxLayout, QFrame, QVBoxLayout
from qfluentwidgets import MessageBoxBase, PushButton, BodyLabel, CommandBar, Action
from qfluentwidgets import FluentIcon as FIF

from app.cards.pure_lesson_card import PureLessonCard


class LessonConflictDialog(MessageBoxBase):
    def __init__(self, conflict_courses, parent=None):
        super().__init__(parent)

        self.conflict_courses = conflict_courses
        # 是否选择了远端的课程，如果选择了，则为 True；否则为 False
        # 此列表的长度和 conflict_courses 一样，每个元素对应一个冲突课程
        self.selection = []
        # 正在展示的冲突课程的索引
        self.current_index = 0

        # 爆改样式，把下面的按钮组去掉，改成点击遮罩层就关闭
        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)

        self.descriptionLabel = BodyLabel(self.tr("获取到的课程与您手动创建的课程冲突，请选择保留的课程"), self)

        # 展示两个课程详情对比
        self.compareFrame = QFrame(self)
        self.compareLayout = QHBoxLayout(self.compareFrame)

        self.leftFrame = QFrame(self)
        self.leftLayout = QVBoxLayout(self.leftFrame)

        self.rightFrame = QFrame(self)
        self.rightLayout = QVBoxLayout(self.rightFrame)

        self.leftLessonCard = PureLessonCard(self.conflict_courses[0][0], parent=self)
        self.rightLessonCard = PureLessonCard(self.conflict_courses[0][1], parent=self)

        self.leftButton = PushButton(self.tr("选择新的课程"), self)
        self.rightButton = PushButton(self.tr("选择本地课程"), self)
        self.leftButton.clicked.connect(self.onLeftButtonClicked)
        self.rightButton.clicked.connect(self.onRightButtonClicked)

        self.leftLayout.addWidget(self.leftLessonCard)
        self.leftLayout.addWidget(self.leftButton)
        self.rightLayout.addWidget(self.rightLessonCard)
        self.rightLayout.addWidget(self.rightButton)
        # 两侧对比控件的宽度必须相同
        self.compareLayout.addWidget(self.leftFrame, stretch=1)
        self.compareLayout.addWidget(self.rightFrame, stretch=1)
        self.leftFrame.setMaximumWidth(int(self.width() / 2))
        self.rightFrame.setMaximumWidth(int(self.width() / 2))

        self.commandBar = CommandBar(self)
        self.commandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.lastAction = Action(FIF.LEFT_ARROW, self.tr("上一个"), self)
        self.cancelAction = Action(FIF.CLOSE, self.tr("取消合并"), self)
        self.commandBar.addAction(self.lastAction)
        self.commandBar.addAction(self.cancelAction)
        self.commandBar.setMinimumWidth(300)

        self.cancelAction.triggered.connect(self.reject)
        self.lastAction.triggered.connect(self.onLastButtonClicked)

        self.viewLayout.addWidget(self.descriptionLabel, alignment=Qt.AlignHCenter)
        self.viewLayout.addWidget(self.compareFrame)
        self.viewLayout.addWidget(self.commandBar, alignment=Qt.AlignHCenter)
        self.viewLayout.setContentsMargins(24, 40, 24, 30)

        self.loadCoursePair(self.conflict_courses[0])

    def loadCoursePair(self, course_pair):
        """
        将一对冲突课程的信息加载到对比对话框中
        :param course_pair: 一对冲突课程
        """
        if len(course_pair) != 2:
            raise ValueError("course_pair must be a tuple of two CourseInstance")

        if self.current_index == 0:
            self.lastAction.setEnabled(False)

        self.leftLessonCard.course = course_pair[0]
        self.rightLessonCard.course = course_pair[1]
        self.leftLessonCard.week_numbers = course_pair[0].week_numbers
        self.rightLessonCard.week_numbers = course_pair[1].week_numbers
        self.leftLessonCard.loadFromCourse()
        self.rightLessonCard.loadFromCourse()

    def resizeEvent(self, event):
        self.leftFrame.setMaximumWidth(int(self.width() / 2))
        self.rightFrame.setMaximumWidth(int(self.width() / 2))

    @pyqtSlot()
    def onLastButtonClicked(self):
        """
        当点击上一个按钮时，触发此方法
        """
        self.current_index -= 1
        self.selection.pop()
        if self.current_index == 0:
            self.lastAction.setEnabled(False)
        self.loadCoursePair(self.conflict_courses[self.current_index])

    @pyqtSlot()
    def onLeftButtonClicked(self):
        """
        当选择了远端的课程时，触发此方法
        """
        self.selection.append(True)
        self.current_index += 1
        self.lastAction.setEnabled(True)
        if self.current_index == len(self.conflict_courses):
            self.accept()
        else:
            self.loadCoursePair(self.conflict_courses[self.current_index])

    @pyqtSlot()
    def onRightButtonClicked(self):
        """
        当选择了本地的课程时，触发此方法
        """
        self.selection.append(False)
        self.current_index += 1
        self.lastAction.setEnabled(True)
        if self.current_index == len(self.conflict_courses):
            self.accept()
        else:
            self.loadCoursePair(self.conflict_courses[self.current_index])
