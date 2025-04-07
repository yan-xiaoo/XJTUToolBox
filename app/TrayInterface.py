# 托盘界面
from PyQt5.QtCore import pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication


class TrayInterface(QSystemTrayIcon):
    """
    托盘界面
    """
    # 显示主页
    main_interface = pyqtSignal()
    # 课表查询页面
    schedule_interface = pyqtSignal()
    # 考勤查询界面
    attendance_interface = pyqtSignal()
    # 成绩查询界面
    score_interface = pyqtSignal()
    # 评教界面
    judge_interface = pyqtSignal()
    # 通知界面
    notice_interface = pyqtSignal()

    def __init__(self, icon):
        super().__init__()

        self.menu = QMenu()
        self.mainPageAction = QAction(self.tr("显示界面"), self)
        self.scheduleAction = QAction(self.tr("课表"), self)
        self.attendanceAction = QAction(self.tr("考勤"), self)
        self.scoreAction = QAction(self.tr("成绩"), self)
        self.judgeAction = QAction(self.tr("评教"), self)
        self.noticeAction = QAction(self.tr("通知"), self)
        self.quitAction = QAction(self.tr("退出"), self)
        self.mainPageAction.triggered.connect(lambda: self.main_interface.emit())
        self.scheduleAction.triggered.connect(lambda: self.schedule_interface.emit())
        self.attendanceAction.triggered.connect(lambda: self.attendance_interface.emit())
        self.scoreAction.triggered.connect(lambda: self.score_interface.emit())
        self.judgeAction.triggered.connect(lambda: self.judge_interface.emit())
        self.noticeAction.triggered.connect(lambda: self.notice_interface.emit())
        self.quitAction.triggered.connect(self.quit)

        self.menu.addAction(self.mainPageAction)
        self.menu.addSeparator()
        self.menu.addAction(self.scheduleAction)
        self.menu.addAction(self.attendanceAction)
        self.menu.addAction(self.scoreAction)
        self.menu.addAction(self.judgeAction)
        self.menu.addAction(self.noticeAction)
        self.menu.addSeparator()
        self.menu.addAction(self.quitAction)

        self.setContextMenu(self.menu)
        self.setIcon(icon)

    @pyqtSlot()
    def quit(self):
        """
        退出主界面
        """
        QApplication.instance().quit()
