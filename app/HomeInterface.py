from PyQt5.QtCore import Qt
from qfluentwidgets import ScrollArea, TitleLabel
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from .utils import accounts, StyleSheet
from .cards.link_card import LinkCardView, LinkCard


class HomeFrame(QWidget):
    """在存在账户时，显示的主界面"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeFrame")
        self.vBoxLayout = QVBoxLayout(self)
        self.title = TitleLabel(self.tr("仙交百宝箱"), self)
        self.vBoxLayout.addWidget(self.title, alignment=Qt.AlignTop)
        self.title.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.setSpacing(0)

        self.linkCardView = LinkCardView(self)
        self.vBoxLayout.addWidget(self.linkCardView, alignment=Qt.AlignTop)
        if accounts.empty():
            self.accountCard = LinkCard("assets/icons/login.png", self.tr("开始使用"),
                                        self.tr("添加你的第一个账户"))
            self.linkCardView.addCard(self.accountCard)
            self.accountCard.cardClicked.connect(lambda: main_window.switchTo(main_window.account_interface))

        self.tableCard = LinkCard("assets/icons/table.png", self.tr("课程表"),
                                  self.tr("查看你的每周课表"))
        self.tableCard.setBackgroundColor(LinkCard.LinkCardColor.RED)
        self.linkCardView.addCard(self.tableCard)
        self.attendanceCard = LinkCard("assets/icons/attendance.png", self.tr("考勤"),
                                       self.tr("查看你的考勤信息"))
        self.attendanceCard.setBackgroundColor(LinkCard.LinkCardColor.PURPLE)
        self.attendanceCard.cardClicked.connect(lambda: main_window.switchTo(main_window.attendance_interface))
        self.linkCardView.addCard(self.attendanceCard)


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
