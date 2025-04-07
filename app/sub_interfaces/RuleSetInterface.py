from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout
from qfluentwidgets import SubtitleLabel, LineEdit, PrimaryPushButton, HyperlinkButton

from ..components.RuleLine import RuleLine
from notification import Ruleset, Filter


class RuleSetInterface(QFrame):
    """
    添加和修改通知过滤规则的页面
    """
    # 退出此界面
    quit = pyqtSignal()
    # 编辑完成
    finishEdit = pyqtSignal(Ruleset)

    def __init__(self, ruleset=None, all_rulesets=None, parent=None):
        """
        创建一个添加和修改规则的页面
        :param ruleset: 需要修改的规则集，如果为 None，则表示添加新的规则集
        :param all_rulesets: 同来源所有的规则集，主要用于生成名称
        :param parent: 父组件
        """
        super().__init__(parent)

        self.setObjectName('RuleSetInterface')

        if ruleset is None:
            ruleset = Ruleset()
        self.ruleset = ruleset

        self.vBoxLayout = QVBoxLayout(self)
        self.titleLabel = SubtitleLabel(self.tr("编辑规则") if ruleset.filters else self.tr("添加规则"), self)
        self.vBoxLayout.addWidget(self.titleLabel, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addStretch()

        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText(self.tr("规则名称"))
        if ruleset.name:
            # 如果规则集已经存在，则使用已有的名称
            self.nameEdit.setText(ruleset.name)
        else:
            if all_rulesets is not None:
                all_names = [one.name for one in all_rulesets]
                i = 1
                while True:
                    name = self.tr("规则") + str(i)
                    if name not in all_names:
                        break
                    i += 1
                self.nameEdit.setText(name)
            else:
                # 如果没有其他规则集，则使用默认名称
                self.nameEdit.setText(self.tr("规则") + str(1))

        self.nameEdit.setMinimumWidth(200)
        self.vBoxLayout.addWidget(self.nameEdit, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addStretch()

        self.filterLayout = QVBoxLayout()
        self.ruleLines = []
        for filter_ in ruleset.filters:
            # 这里需要添加一个过滤器的编辑组件
            line = RuleLine(filter_, self)
            line.deleted.connect(self.onRuleLineDeleted)
            self.ruleLines.append(line)
            self.filterLayout.addWidget(line)

        self.vBoxLayout.addLayout(self.filterLayout)
        self.addButton = HyperlinkButton(self)
        self.addButton.setText(self.tr("添加过滤条件"))
        self.addButton.clicked.disconnect(self.addButton._onClicked)
        self.addButton.clicked.connect(self.onAddRuleLine)
        self.vBoxLayout.addWidget(self.addButton, alignment=Qt.AlignHCenter)

        self.vBoxLayout.addStretch()
        self.completeButton = PrimaryPushButton(self.tr("完成"), self)
        self.completeButton.clicked.connect(self.onCompleteButtonClicked)
        self.vBoxLayout.addWidget(self.completeButton)
        self.vBoxLayout.addSpacing(20)

    @pyqtSlot()
    def onAddRuleLine(self):
        """
        当用户添加一条规则时，更新规则列表
        """
        line = RuleLine(filter_=None, parent=self)
        self.ruleLines.append(line)
        self.filterLayout.addWidget(line)
        # 连接信号
        line.deleted.connect(self.onRuleLineDeleted)

    @pyqtSlot(object)
    def onRuleLineDeleted(self, filter_: RuleLine):
        """
        当用户删除一条规则时，更新规则列表
        :param filter_: 被删除的过滤器组件
        :return:
        """
        if filter_.filter is not None:
            self.ruleset.remove_filter(filter_.filter)
        # 删除对应的规则行
        self.filterLayout.removeWidget(filter_)
        filter_.deleteLater()
        self.ruleLines.remove(filter_)

    @pyqtSlot()
    def onCompleteButtonClicked(self):
        """
        当用户点击完成按钮时，发出信号
        :return:
        """
        if not self.nameEdit.text() and not self.ruleLines:
            # 如果没有输入名称和规则，则填写不完整，直接退出
            self.quit.emit()
            return

        self.ruleset.name = self.nameEdit.text()
        self.ruleset.filters = []
        for one in self.ruleLines:
            filter_ = one.get_representation()
            if filter_ is not None:
                self.ruleset.add_filter(filter_)
            else:
                # 如果没有输入宾语，则填写不完整，不继续
                return
        self.quit.emit()
        self.finishEdit.emit(self.ruleset)
