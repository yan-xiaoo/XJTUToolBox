import subprocess

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton

from app.school_ai_launcher import school_ai_browser_command
from app.school_ai_policy import JIAOXIAOZHI_URL
from .components.CampusPage import CampusPage


class JiaoxiaozhiInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("jiaoxiaozhiInterface", "交晓智", "打开学校官方校园问答平台", parent)
        self.hint = BodyLabel(
            self.tr("交晓智是学校官方智能问答。独立窗口使用 Qt 6 WebEngine；如果本机没有该组件，会改用系统浏览器。"),
            self.view,
        )
        self.hint.setWordWrap(True)
        self.vBoxLayout.addWidget(self.hint)
        self.launchButton = PrimaryPushButton(self.tr("打开交晓智"), self.view)
        self.launchButton.setFixedWidth(160)
        self.browserButton = PushButton(self.tr("用系统浏览器打开"), self.view)
        self.browserButton.setFixedWidth(180)
        self.launchButton.clicked.connect(self.launch)
        self.browserButton.clicked.connect(self.open_system_browser)
        self.vBoxLayout.addWidget(self.launchButton, alignment=Qt.AlignLeft)
        self.vBoxLayout.addWidget(self.browserButton, alignment=Qt.AlignLeft)
        self.vBoxLayout.addStretch(1)

    def launch(self):
        command = school_ai_browser_command()
        if command is None:
            self.open_system_browser()
            self.info(self.tr("已回退"), self.tr("未找到独立浏览器组件，已用系统浏览器打开"))
            return
        executable, args = command
        try:
            subprocess.Popen([executable, *args])
            self.success(self.tr("已打开"), self.tr("交晓智窗口已启动"))
        except OSError as exc:
            self.warn(self.tr("启动失败"), str(exc))
            self.open_system_browser()

    def open_system_browser(self):
        QDesktopServices.openUrl(QUrl(JIAOXIAOZHI_URL))
