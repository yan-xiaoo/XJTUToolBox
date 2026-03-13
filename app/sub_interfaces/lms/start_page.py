from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout
from qfluentwidgets import BodyLabel, PrimaryPushButton


class LMSStartPage(QFrame):
    # 请求主容器开始加载课程列表。
    queryCoursesRequested = pyqtSignal()

    def __init__(self, parent=None):
        """初始化起始页组件。"""
        super().__init__(parent)
        self.setObjectName("startPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.startFrame = QFrame(self)
        self.startFrameLayout = QVBoxLayout(self.startFrame)

        self.startLabel = BodyLabel(self.tr("还没有课程信息"), self.startFrame)
        self.startButton = PrimaryPushButton(self.tr("查询我的课程"), self.startFrame)
        self.startButton.setFixedWidth(150)
        self.startButton.clicked.connect(self.queryCoursesRequested.emit)

        self.startFrameLayout.addWidget(self.startLabel, alignment=Qt.AlignHCenter)
        self.startFrameLayout.addWidget(self.startButton, alignment=Qt.AlignHCenter)

        layout.addStretch(1)
        layout.addWidget(self.startFrame, alignment=Qt.AlignVCenter | Qt.AlignHCenter)
        layout.addStretch(1)

    def setInteractionEnabled(self, enabled: bool):
        """设置页面交互状态。

        :param enabled: 为 True 时启用“查询我的课程”按钮；为 False 时禁用。
        :return: 无返回值。
        """
        self.startButton.setEnabled(enabled)

    def reset(self):
        """重置起始页状态到初始可交互状态。

        :return: 无返回值。
        """
        self.setInteractionEnabled(True)
