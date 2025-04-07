from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout
from qfluentwidgets import BodyLabel, SubtitleLabel, PrimaryPushButton

from ..components.NoticeRuleCard import NoticeRuleCard, AddRuleCard
from notification import Source, NotificationManager, Ruleset
from ..utils.cache import dataManager


class NoticeRuleInterface(QFrame):
    """
    本类为设置通知来源过滤规则的具体页面
    """
    # 修改规则集的信号
    editRuleSet = pyqtSignal(Ruleset, Source)
    # 返回上一级的信号
    quit = pyqtSignal()

    def __init__(self, manager: NotificationManager, source: Source, parent=None):
        """
        创建一个设置过滤规则的页面
        :param manager: 通知管理器
        :param source: 目前设置规则的通知来源
        :param parent: 父组件
        """
        super().__init__(parent)

        self.setObjectName('NoticeRuleInterface')

        self.manager = manager
        self.source = source

        self.vBoxLayout = QVBoxLayout(self)
        self.cards = []

        # 标题，通知来源的名称
        self.titleLabel = SubtitleLabel(source.value + self.tr("网站的过滤规则"), self)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.addWidget(self.titleLabel, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addStretch()

        self.addRuleCard = AddRuleCard(self)
        self.addRuleCard.clicked.connect(self.onAddRuleSet)
        self.vBoxLayout.addWidget(self.addRuleCard)
        self.cardLayout = QVBoxLayout()
        if source in self.manager.ruleset:
            for one in self.manager.ruleset[source]:
                card = NoticeRuleCard(one, self)
                card.editRuleSet.connect(self.onEditRuleSet)
                card.deleteRuleSet.connect(self.onDeleteRuleSet)
                self.cards.append(card)
                self.cardLayout.addWidget(card)

        self.vBoxLayout.addLayout(self.cardLayout)
        self.vBoxLayout.addStretch()
        self.completeButton = PrimaryPushButton(self.tr("完成"), self)
        self.completeButton.clicked.connect(lambda: self.quit.emit())
        self.hintLabel = BodyLabel(self.tr("满足任何一条规则的通知就会显示"), self)
        self.vBoxLayout.addWidget(self.hintLabel, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.completeButton)
        self.vBoxLayout.addSpacing(20)

    @pyqtSlot()
    def onAddRuleSet(self):
        self.editRuleSet.emit(Ruleset(), self.source)

    @pyqtSlot(Ruleset)
    def onEditRuleSet(self, ruleset: Ruleset):
        self.editRuleSet.emit(ruleset, self.source)

    @pyqtSlot(Ruleset)
    def onEditFinish(self, ruleset: Ruleset):
        current_card_sets = [one.ruleset for one in self.cards]
        if ruleset in current_card_sets:
            # 如果规则集已经存在，直接更新
            for one in self.cards:
                if one.ruleset == ruleset:
                    one.updateDisplay()
                    break
        else:
            # 如果规则集不存在，添加新的卡片
            card = NoticeRuleCard(ruleset, self)
            card.editRuleSet.connect(self.onEditRuleSet)
            card.deleteRuleSet.connect(self.onDeleteRuleSet)
            self.cards.append(card)
            self.cardLayout.addWidget(card)
            self.manager.add_ruleset(self.source, ruleset)
        # 更新配置文件
        dataManager.write_json("notification_config.json", self.manager.dump_config(), allow_overwrite=True)

    @pyqtSlot(Ruleset)
    def onDeleteRuleSet(self, ruleset: Ruleset):
        # 删除规则
        self.manager.remove_ruleset(self.source, ruleset)
        # 删除卡片
        one = None
        for one in self.cards:
            if one.ruleset == ruleset:
                one.deleteLater()
                self.vBoxLayout.removeWidget(one)
                break
        if one is not None:
            self.cards.remove(one)
