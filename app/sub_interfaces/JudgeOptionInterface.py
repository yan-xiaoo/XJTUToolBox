from collections.abc import Callable

from PyQt5.QtCore import pyqtSlot, Qt, QObject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import ScrollArea, MessageBoxBase, SubtitleLabel, ToolTipFilter, ComboBox, ToolTipPosition, \
    PlainTextEdit, FlyoutViewBase, BodyLabel, PrimaryPushButton, Flyout, CaptionLabel, PushButton

from app.threads.JudgeThread import JudgeChoice
from app.threads.ProcessWidget import ProcessThread
from app.utils import StyleSheet, accounts, AccountDataManager
from ehall import Questionnaire, QuestionnaireTemplate


class _CustomFlyoutView(FlyoutViewBase):

    def __init__(self,on_confirm: Callable, on_cancel: Callable, parent=None):
        super().__init__(parent)
        # 在选择”撤销“和”仍然更改“时，分别执行 on_cancel 和 on_confirm 函数
        self._on_cancel = on_cancel
        self._on_confirm = on_confirm
        self.vBoxLayout = QVBoxLayout(self)
        self.buttonHBoxLayout = QHBoxLayout()
        self.label = BodyLabel(self.tr('此功能仅在问卷填写失败时使用，请不要随意更改'), self)
        self.confirm_button = PrimaryPushButton(self.tr('仍然更改'), self)
        self.cancel_button = PushButton(self.tr("撤销"), self)

        self.confirm_button.clicked.connect(self.onConfirmButtonClicked)
        self.cancel_button.clicked.connect(self.onCancelButtonClicked)

        self.confirm_button.setFixedWidth(140)
        self.buttonHBoxLayout.addWidget(self.confirm_button)
        self.buttonHBoxLayout.addWidget(self.cancel_button)
        self.vBoxLayout.setSpacing(12)
        self.vBoxLayout.setContentsMargins(20, 16, 20, 16)
        self.vBoxLayout.addWidget(self.label)
        self.vBoxLayout.addLayout(self.buttonHBoxLayout)

    @pyqtSlot()
    def onConfirmButtonClicked(self):
        self._on_confirm()
        self.parent().close()

    @pyqtSlot()
    def onCancelButtonClicked(self):
        self._on_cancel()
        self.parent().close()


class JudgeCacheManager(QObject):
    """
    利用 CacheManager 类，将所有评教缓存信息统一存储到一个文件中
    """
    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
            cls.__instance.__init__()
            cls.__instance.caches = {}
            try:
                cls.__instance.load()
            except Exception:
                pass
            accounts.currentAccountChanged.connect(cls.__instance.onCurrentAccountChanged, Qt.UniqueConnection)

        return cls.__instance

    def add(self, questionnaire: Questionnaire, score: QuestionnaireTemplate.Score, class_type: QuestionnaireTemplate.Type, comment: str):
        # 教学班 ID+被评人代码组成唯一标识
        uuid = questionnaire.JXBID + questionnaire.BPR
        self.caches[uuid] = {
            "score": score.value,
            "class_type": class_type.value,
            "comment": comment
        }

    def delete(self, questionnaire: Questionnaire):
        uuid = questionnaire.JXBID + questionnaire.BPR
        self.caches.pop(uuid)

    def get(self, questionnaire: Questionnaire):
        uuid = questionnaire.JXBID + questionnaire.BPR
        data = self.caches.get(uuid, None)
        if data is not None:
            data["score"] = QuestionnaireTemplate.Score(data["score"])
            data["class_type"] = QuestionnaireTemplate.Type(data["class_type"])
        return data

    def clear(self):
        self.caches.clear()

    def save(self):
        """
        写入缓存到当前账户的缓存文件中
        """
        cache = AccountDataManager(accounts.current)
        cache.write_json("judge_cache.json", self.caches, True)

    def load(self):
        """
        从当前账户的缓存文件中读取缓存
        """
        cache = AccountDataManager(accounts.current)
        self.caches = cache.read_json("judge_cache.json")

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        try:
            self.load()
        except Exception:
            pass


class JudgeOptionInterface(ScrollArea):
    """
    评教选项界面，可以在此界面选择评教评分、填写自定义评语等。
    """
    def __init__(self, questionnaire: Questionnaire, thread_: ProcessThread, finished: bool, parent=None):
        super().__init__(parent=parent)
        self.questionnaire = questionnaire
        self.thread_ = thread_
        self.finished_ = finished

        self.setObjectName("JudgeOptionInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.title = SubtitleLabel(questionnaire.KCM + " " + questionnaire.BPJS, self)
        self.detailLabel = CaptionLabel(questionnaire.WJMC, self)
        self.detailLabel.setTextColor("#606060", "#d2d2d2")

        # 课程类型框和分数框部分
        self.optionHLayout = QHBoxLayout()
        self.scoreBox = ComboBox(self.view)
        self.classTypeBox = ComboBox(self.view)
        # 记录上一次选择的课程类型
        self.last_class_index = None

        # 设置工具提示
        self.classTypeBox.setToolTip(self.tr("选择问卷的类型"))
        self.scoreBox.setToolTip(self.tr("选择预先设置的问卷分数"))
        self.classTypeBox.setToolTipDuration(1000)
        self.scoreBox.setToolTipDuration(1000)
        self.scoreBox.installEventFilter(ToolTipFilter(self.scoreBox, showDelay=300, position=ToolTipPosition.TOP))
        self.classTypeBox.installEventFilter(
            ToolTipFilter(self.classTypeBox, showDelay=300, position=ToolTipPosition.TOP))

        # 设置可选的选项
        type_dict = {QuestionnaireTemplate.Type.THEORY: "理论课",
                     QuestionnaireTemplate.Type.IDEOLOGY: "思政课",
                     QuestionnaireTemplate.Type.GENERAL: "通识课",
                     QuestionnaireTemplate.Type.EXPERIMENT: "实验课",
                     QuestionnaireTemplate.Type.PROJECT: "项目设计课",
                     QuestionnaireTemplate.Type.PHYSICAL: "体育课"}
        for one in QuestionnaireTemplate.Type:
            self.classTypeBox.addItem(self.tr(type_dict[one]), userData=one)

        # 设置分数的可选选项
        score_dict = {QuestionnaireTemplate.Score.HUNDRED: "100分",
                      QuestionnaireTemplate.Score.EIGHTY: "80分",
                      QuestionnaireTemplate.Score.SIXTY: "60分",
                      QuestionnaireTemplate.Score.FORTY: "40分"}
        for one in QuestionnaireTemplate.Score:
            self.scoreBox.addItem(self.tr(score_dict[one]), userData=one)

        # 自动设置课程类型
        for item in self.classTypeBox.items:
            if item.text in questionnaire.WJMC:
                self.classTypeBox.setCurrentIndex(self.classTypeBox.items.index(item))
                self.last_class_index = self.classTypeBox.currentIndex()
                break

        self.textArea = PlainTextEdit(self.view)
        if "理论课" in questionnaire.WJMC:
            self.textArea.setPlaceholderText(self.tr("（可以留空）请写下老师教学方面的优点或有待改进的地方，以及对所使用教材的意见"))
        else:
            self.textArea.setPlaceholderText(self.tr("（可以留空）请写下老师教学方面的优点以及有待改进的地方"))

        self.optionHLayout.addWidget(self.scoreBox)
        self.optionHLayout.addWidget(self.classTypeBox)

        self.vBoxLayout.addWidget(self.title, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.detailLabel, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addLayout(self.optionHLayout)
        self.vBoxLayout.addWidget(self.textArea, stretch=1)

        # 尝试读取缓存
        self.load()

        self.classTypeBox.currentTextChanged.connect(self.onModifyClassTypeClicked)
        self.textArea.setFocus()

        StyleSheet.JUDGE_OPTION_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def save(self):
        """
        保存当前评教信息到缓存中
        """
        cache = JudgeCacheManager()
        cache.add(self.questionnaire, self.scoreBox.currentData(), self.classTypeBox.currentData(), self.textArea.toPlainText())
        cache.save()

    def load(self):
        """
        从缓存中读取当前评教信息
        """
        cache = JudgeCacheManager()
        data = cache.get(self.questionnaire)
        if data is not None:
            self.scoreBox.setCurrentIndex(self.scoreBox.findData(data["score"]))
            self.classTypeBox.setCurrentIndex(self.classTypeBox.findData(data["class_type"]))
            self.textArea.setPlainText(data["comment"])

    @pyqtSlot()
    def cancelModifyClassType(self):
        self.classTypeBox.setCurrentIndex(self.last_class_index)

    @pyqtSlot()
    def confirmModifyClassType(self):
        self.last_class_index = self.classTypeBox.currentIndex()

    @pyqtSlot()
    def onModifyClassTypeClicked(self):
        # 如果此修改是被下方提示中的「撤销」按钮触发的，则不执行任何操作
        if self.classTypeBox.currentIndex() == self.last_class_index:
            return
        flyout = Flyout.make(
            target=self.classTypeBox,
            view=_CustomFlyoutView(on_confirm=self.confirmModifyClassType, on_cancel=self.cancelModifyClassType),
            parent=self
        )
        flyout.closed.connect(self.cancelModifyClassType)

    @pyqtSlot()
    def onSubmitButtonClicked(self):
        self.thread_.questionnaire = self.questionnaire
        template = QuestionnaireTemplate.from_file(self.classTypeBox.currentData(),
                                                   self.scoreBox.currentData())
        for one_data in template.data:
            if one_data.TXDM != '01':
                one_data.ZGDA = self.textArea.toPlainText() if self.textArea.toPlainText() else self.tr("无")
        self.thread_.template = template

        if self.finished_:
            self.thread_.choice = JudgeChoice.EDIT
        else:
            self.thread_.choice = JudgeChoice.JUDGE
        self.thread_.start()


class JudgeOptionMessageBox(MessageBoxBase):
    """
    将评教选择界面封装为对话框，用于显示评教选项。
    """
    def __init__(self, questionnaire: Questionnaire, thread_: ProcessThread, finished: bool, parent=None):
        super().__init__(parent)

        self.interface = JudgeOptionInterface(questionnaire, thread_, finished, self)
        self.viewLayout.addWidget(self.interface, 1)

        self.yesButton.setText(self.tr("提交"))
        self.cancelButton.setText(self.tr("保存但不提交"))

        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self.onSaveButtonClicked)
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self.onYesButtonClicked)

    @pyqtSlot()
    def onSaveButtonClicked(self):
        self.interface.save()
        self.reject()

    @pyqtSlot()
    def onYesButtonClicked(self):
        self.interface.save()
        self.interface.onSubmitButtonClicked()
        self.accept()
