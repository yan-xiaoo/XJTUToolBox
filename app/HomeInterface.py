from PyQt5.QtCore import Qt, pyqtSlot
from qfluentwidgets import ScrollArea, TitleLabel, FluentIcon as FIF, Theme, TogglePushButton, PushButton, InfoBar, InfoBarPosition
from PyQt5.QtWidgets import QVBoxLayout, QWidget, QHBoxLayout
from .utils import accounts, StyleSheet, cfg
from .cards.link_card import LinkCardView, LinkCard
from .sub_interfaces.EncryptDialog import DecryptFrame
from .components.CardManagerDialog import CardManagerDialog


class HomeFrame(QWidget):
    """在存在账户时，显示的主界面"""
    default_layout = ["schedule", "attendance", "score", "judge", "notice", "empty_room"]

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("WelcomeFrame")
        self.vBoxLayout = QVBoxLayout(self)

        self._onlyNotice = None

        # 标题
        self.title = TitleLabel(self.tr("仙交百宝箱"), self)
        self.title.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.addWidget(self.title, alignment=Qt.AlignTop)

        # 控制按钮区域
        self.controlLayout = QHBoxLayout()
        self.controlLayout.setContentsMargins(66, 10, 66, 10)

        # 编辑模式切换按钮
        self.editButton = TogglePushButton(self.tr("编辑"), self)
        self.editButton.setIcon(FIF.EDIT)
        self.editButton.toggled.connect(self.onEditModeToggled)

        # 添加功能按钮
        self.addButton = PushButton(self.tr("添加功能"), self)
        self.addButton.setIcon(FIF.ADD)
        self.addButton.clicked.connect(self.onAddCardClicked)
        self.addButton.hide()  # 默认隐藏

        # 重置布局按钮
        self.resetButton = PushButton(self.tr("重置布局"), self)
        self.resetButton.setIcon(FIF.SYNC)
        self.resetButton.clicked.connect(self.onResetLayoutClicked)
        self.resetButton.hide()  # 默认隐藏

        self.controlLayout.addWidget(self.editButton)
        self.controlLayout.addStretch()
        self.controlLayout.addWidget(self.addButton)
        self.controlLayout.addStretch()
        self.controlLayout.addWidget(self.resetButton)

        # 解密框
        self.decrypt_frame = DecryptFrame(self, self)
        self.decrypt_frame.setMaximumWidth(300)
        if accounts.encrypted:
            self.decrypt_frame.setVisible(True)
        else:
            self.decrypt_frame.setVisible(False)
        self.vBoxLayout.addWidget(self.decrypt_frame, alignment=Qt.AlignHCenter)
        accounts.accountDecrypted.connect(self.onAccountDecrypted)
        accounts.accountCleared.connect(self.onAccountDecrypted)

        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.controlLayout)

        # 设置卡片视图
        self.linkCardView = LinkCardView(self)
        self.setupCards()
        self.loadDefaultCards()

        # 连接信号
        self.linkCardView.cardOrderChanged.connect(self.onCardOrderChanged)
        self.linkCardView.cardDeleted.connect(self.onCardDeleted)

        self.vBoxLayout.addWidget(self.linkCardView, alignment=Qt.AlignTop)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.setSpacing(0)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个成功的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.success(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def warning(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个警告的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.warning(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.warning(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def info(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个信息的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.info(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.info(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def setupCards(self):
        """设置所有可用的卡片定义"""
        available_cards = {
            'account': {
                'icon': "assets/icons/login.png",
                'title': self.tr("开始使用"),
                'content': self.tr("添加你的第一个账户"),
                'callback': lambda: self.main_window.switchTo(self.main_window.account_interface)
            },
            'schedule': {
                'icon': FIF.CALENDAR.icon(theme=Theme.DARK),
                'title': self.tr("课程表"),
                'content': self.tr("查看你的每周课表"),
                'callback': lambda: self.main_window.switchTo(self.main_window.schedule_interface),
                'color': LinkCard.LinkCardColor.RED
            },
            'attendance': {
                'icon': "assets/icons/attendance.png",
                'title': self.tr("考勤"),
                'content': self.tr("查看你的考勤信息"),
                'callback': lambda: self.main_window.switchTo(self.main_window.attendance_interface),
                'color': LinkCard.LinkCardColor.PURPLE
            },
            'score': {
                'icon': FIF.EDUCATION.icon(theme=Theme.DARK),
                'title': self.tr("成绩"),
                'content': self.tr("查看你各学期的成绩"),
                'callback': lambda: self.main_window.switchTo(self.main_window.score_interface),
                'color': LinkCard.LinkCardColor.BLUE
            },
            'judge': {
                'icon': FIF.BOOK_SHELF.icon(theme=Theme.DARK),
                'title': self.tr("评教"),
                'content': self.tr("快速完成本学期评教"),
                'callback': lambda: self.main_window.switchTo(self.main_window.judge_interface),
                'color': LinkCard.LinkCardColor.YELLOW
            },
            'notice': {
                'icon': FIF.DICTIONARY.icon(theme=Theme.DARK),
                'title': self.tr("通知"),
                'content': self.tr("查看学校网站的新通知"),
                'callback': lambda: self.main_window.switchTo(self.main_window.notice_interface),
                'color': LinkCard.LinkCardColor.GREEN
            },
            'empty_room': {
                'icon': FIF.LAYOUT.icon(theme=Theme.DARK),
                'title': self.tr("空闲教室"),
                'content': self.tr("查询当前空闲的教室"),
                'callback': lambda: self.main_window.switchTo(self.main_window.empty_room_interface),
                'color': LinkCard.LinkCardColor.ORANGE
            }
        }

        self.linkCardView.setAvailableCards(available_cards)

    def loadDefaultCards(self):
        """加载默认卡片布局"""
        # 从配置文件加载保存的布局
        saved_layout = cfg.get(cfg.cardLayout)

        if saved_layout:
            # 使用保存的布局
            for card_id in saved_layout:
                self.addCardWithColor(card_id)
        else:
            # 使用默认布局
            default_cards = self.default_layout[:]

            # 如果没有账户，先添加账户卡片
            if accounts.empty():
                default_cards.insert(0, 'account')

            for card_id in default_cards:
                self.addCardWithColor(card_id)

    def addCardWithColor(self, card_id: str):
        """添加卡片并设置颜色"""
        if self.linkCardView.addCardById(card_id):
            # 设置卡片颜色
            for card in self.linkCardView._cards:
                if card.card_id == card_id:
                    card_def = self.linkCardView._available_cards.get(card_id, {})
                    if 'color' in card_def:
                        card.setBackgroundColor(card_def['color'])
                    break

    @pyqtSlot(bool)
    def onEditModeToggled(self, checked: bool):
        """编辑模式切换"""
        self.linkCardView.setEditMode(checked)

        # 显示/隐藏编辑相关按钮
        self.addButton.setVisible(checked)
        self.resetButton.setVisible(checked)

        if checked:
            self.editButton.setText(self.tr("完成编辑"))
            self.info(
                self.tr("编辑模式"),
                self.tr("现在可以拖拽卡片重新排序，或点击删除按钮移除卡片"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self
            )
        else:
            self.editButton.setText(self.tr("编辑"))
            self.success(
                self.tr("保存成功"),
                self.tr("布局更改已保存"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )
            # 保存当前布局
            self.saveCardSettings()

    @pyqtSlot()
    def onAddCardClicked(self):
        """添加卡片按钮点击"""
        available_cards = self.linkCardView.getAvailableCardsForAddition()

        if not available_cards:
            self.warning(
                self.tr("无可添加卡片"),
                self.tr("所有功能卡片都已添加到主界面"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )
            return

        # 显示卡片选择对话框
        dialog = CardManagerDialog(available_cards, self)
        dialog.cardsSelected.connect(self.onCardsSelected)
        dialog.exec()

    @pyqtSlot()
    def onResetLayoutClicked(self):
        """重置布局按钮点击"""
        # 移除所有卡片
        cards_to_remove = self.linkCardView._cards[:]
        for card in cards_to_remove:
            self.linkCardView.removeCard(card)

        # 重新添加默认卡片
        default_cards = self.default_layout[:]
        if accounts.empty():
            default_cards.insert(0, 'account')  # 如果没有账户，先添加账户卡片

        for card_id in default_cards:
            self.addCardWithColor(card_id)

        self.success(
            self.tr("重置成功"),
            self.tr("布局已重置为默认设置"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    @pyqtSlot(list)
    def onCardsSelected(self, card_ids: list):
        """卡片选择完成"""
        added_count = 0
        for card_id in card_ids:
            if self.addCardWithColor(card_id):
                added_count += 1

        if added_count > 0:
            self.success(
                self.tr("添加成功"),
                f"{self.tr('已添加')} {added_count} {self.tr('个功能卡片')}",
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self
            )

    @pyqtSlot(list)
    def onCardOrderChanged(self, order: list):
        """卡片顺序改变"""
        # 保存到配置
        self.saveCardSettings()

    @pyqtSlot(str)
    def onCardDeleted(self, card_id: str):
        """卡片被删除"""
        self.info(
            self.tr("卡片已移除"),
            self.tr("可通过'添加功能'按钮重新添加"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self
        )

    def saveCardSettings(self):
        """保存卡片设置到配置文件"""
        order = self.linkCardView.getCardOrder()
        no_account_default_layout = ['account'] + self.default_layout
        if order == self.default_layout or order == no_account_default_layout:
            # 如果顺序与默认布局相同，则不保存
            cfg.set(cfg.cardLayout, [])
        else:
            cfg.set(cfg.cardLayout, order)

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
