from PyQt5.QtCore import Qt, pyqtSlot
from qfluentwidgets import ScrollArea, TitleLabel, FluentIcon as FIF, Theme
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from .utils import accounts, StyleSheet
from .cards.link_card import LinkCardView, LinkCard
from .sub_interfaces.EncryptDialog import DecryptFrame


class HomeFrame(QWidget):
    """在存在账户时，显示的主界面"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeFrame")
        self.vBoxLayout = QVBoxLayout(self)
        self.title = TitleLabel(self.tr("仙交百宝箱"), self)
        self.vBoxLayout.addWidget(self.title, alignment=Qt.AlignTop)
        self.vBoxLayout.addStretch(1)
        self.title.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.setSpacing(0)

        self.decrypt_frame = DecryptFrame(self, self)
        self.decrypt_frame.setMaximumWidth(300)
        if accounts.encrypted:
            self.decrypt_frame.setVisible(True)
        else:
            self.decrypt_frame.setVisible(False)
        self.vBoxLayout.addWidget(self.decrypt_frame, alignment=Qt.AlignHCenter)
        accounts.accountDecrypted.connect(self.onAccountDecrypted)
        accounts.accountCleared.connect(self.onAccountDecrypted)

        self.linkCardView = LinkCardView(self)
        if accounts.empty():
            self.accountCard = LinkCard("assets/icons/login.png", self.tr("开始使用"),
                                        self.tr("添加你的第一个账户"))
            self.linkCardView.addCard(self.accountCard)
            self.accountCard.cardClicked.connect(lambda: main_window.switchTo(main_window.account_interface))

        self.tableCard = LinkCard(FIF.CALENDAR.icon(theme=Theme.DARK), self.tr("课程表"),
                                  self.tr("查看你的每周课表"))
        self.tableCard.setBackgroundColor(LinkCard.LinkCardColor.RED)
        self.tableCard.cardClicked.connect(lambda: main_window.switchTo(main_window.schedule_interface))
        self.linkCardView.addCard(self.tableCard)
        self.attendanceCard = LinkCard("assets/icons/attendance.png", self.tr("考勤"),
                                       self.tr("查看你的考勤信息"))
        self.attendanceCard.setBackgroundColor(LinkCard.LinkCardColor.PURPLE)
        self.attendanceCard.cardClicked.connect(lambda: main_window.switchTo(main_window.attendance_interface))
        self.linkCardView.addCard(self.attendanceCard)
        self.scoreCard = LinkCard(FIF.EDUCATION.icon(theme=Theme.DARK), self.tr("成绩"),
                                  self.tr("查看你各学期的成绩"))
        self.scoreCard.setBackgroundColor(LinkCard.LinkCardColor.BLUE)
        self.scoreCard.cardClicked.connect(lambda: main_window.switchTo(main_window.score_interface))
        self.linkCardView.addCard(self.scoreCard)
        self.judgeCard = LinkCard(FIF.BOOK_SHELF.icon(theme=Theme.DARK), self.tr("评教"),
                                  self.tr("快速完成本学期评教"))
        self.judgeCard.setBackgroundColor(LinkCard.LinkCardColor.YELLOW)
        self.judgeCard.cardClicked.connect(lambda: main_window.switchTo(main_window.judge_interface))
        self.linkCardView.addCard(self.judgeCard)

        self.vBoxLayout.addWidget(self.linkCardView, alignment=Qt.AlignTop)
        self.vBoxLayout.addStretch(1)

    @pyqtSlot()
    def onAccountDecrypted(self):
        self.decrypt_frame.setVisible(False)


class HomeInterface(ScrollArea):
    """主界面"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)

        self.setObjectName("HomeInterface")
        self.view = HomeFrame(main_window, self)

        self.view.setObjectName("view")

        StyleSheet.HOME_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
