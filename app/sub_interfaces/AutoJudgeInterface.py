from PyQt5.QtCore import Qt, pyqtSlot, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QFrame
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, ComboBox, ScrollArea, PrimaryPushButton, ToolTipFilter, \
    ToolTipPosition, InfoBar, InfoBarPosition, CommandBar, Action, FluentIcon, PushButton, TitleLabel
from ehall import Questionnaire, QuestionnaireTemplate
from .JudgeOptionInterface import JudgeOptionMessageBox
from ..utils import StyleSheet
from ..threads.JudgeThread import JudgeThread, JudgeChoice
from ..threads.ProcessWidget import ProcessDialog
from ..utils import accounts


class JudgeCard(CardWidget):
    def __init__(self, questionnaire: Questionnaire, interface: "AutoJudgeInterface", finished=False, parent=None):
        super().__init__(parent)

        # 用于修改线程信息
        self.thread_ = interface.thread_
        self.parent_ = interface
        self.questionnaire = questionnaire
        self.finished = finished

        if not finished:
            self.titleLabel = BodyLabel(questionnaire.KCM + " " + questionnaire.BPJS, self)
        else:
            self.titleLabel = BodyLabel(questionnaire.KCM + " " + questionnaire.BPJS + " (已完成)", self)
        self.contentLabel = CaptionLabel(questionnaire.WJMC, self)
        if not finished:
            self.submitButton = PrimaryPushButton(self.tr("开始评教"), self)
        else:
            self.submitButton = PrimaryPushButton(self.tr("编辑评教"), self)

        self.submitButton.clicked.connect(self.onJudgeButtonClicked)
        self.submitButton.setMaximumWidth(150)

        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        self.setFixedHeight(73)
        self.contentLabel.setTextColor("#606060", "#d2d2d2")

        self.hBoxLayout.setContentsMargins(20, 11, 20, 11)
        self.hBoxLayout.setSpacing(15)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignVCenter)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)
        self.hBoxLayout.addLayout(self.vBoxLayout)

        self.hBoxLayout.addSpacing(10)
        self.hBoxLayout.addWidget(self.submitButton, 0, Qt.AlignVCenter)

    @pyqtSlot()
    def onJudgeButtonClicked(self):
        dev_interface = JudgeOptionMessageBox(self.questionnaire, self.thread_, self.finished, self.parent_)
        dev_interface.exec()

    def setFinished(self, status):
        self.finished = status
        if status:
            self.submitButton.setText(self.tr("编辑评教"))
            self.titleLabel.setText(self.tr(self.questionnaire.KCM + " " + self.questionnaire.BPJS + " (已完成)"))
        else:
            self.submitButton.setText(self.tr("开始评教"))
            self.titleLabel.setText(self.tr(self.questionnaire.KCM + " " + self.questionnaire.BPJS))


class AutoJudgeInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("autoJudgeInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.commandBar = CommandBar(self)
        self.commandBar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.refreshAction = Action(FluentIcon.SYNC, self.tr("立刻刷新"), self.commandBar)
        self.refreshAction.triggered.connect(self.onStartButtonClicked)
        self.showAllAction = Action(FluentIcon.SEARCH, self.tr("显示已完成的问卷"), self.commandBar, checkable=True,
                                    triggered=self.onShowFinishedQuestionnairesTriggered)
        self.viewAction = Action(FluentIcon.LINK, self.tr("前往 Ehall 查看"), self.commandBar)
        self.viewAction.triggered.connect(self.onViewEhallTriggered)
        self.commandBar.addAction(self.refreshAction)
        self.commandBar.addAction(self.showAllAction)
        self.commandBar.addAction(self.viewAction)
        self.commandBar.setMinimumWidth(500)
        self.vBoxLayout.addWidget(self.commandBar, 1, alignment=Qt.AlignTop | Qt.AlignHCenter)

        self.thread_ = JudgeThread(accounts.current, choice=JudgeChoice.GET_COURSES)
        self.thread_.questionnaires.connect(self.onGetQuestionnaireFinish)
        self.thread_.error.connect(self.onThreadError)
        self.thread_.submitSuccess.connect(self.onSubmitSuccess)
        self.thread_.editSuccess.connect(self.onEditSuccess)
        self.thread_.started.connect(self.onThreadStarted)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        self.processDialog = ProcessDialog(self.thread_, parent, True)

        self.startFrame = QFrame(self.view)
        self.startFrameLayout = QVBoxLayout(self.startFrame)
        self.questionnaireFrame = QFrame(self.view)
        self.questionnaireWidgets = []
        self.finishedQuestionnaireWidgets = []
        self.noQuestionnaireLabel = TitleLabel(self.tr("没有需要完成的问卷"), self.questionnaireFrame)
        self.noQuestionnaireLabel.setVisible(False)

        self.questionnaireFrameLayout = QVBoxLayout(self.questionnaireFrame)

        self.hintLabel = BodyLabel(
            self.tr("使用说明：点击开始评教，选择分数，点击提交即可完成评教。\n"
                    "可以选择输入评语，也可以不输入。\n"
                    "如果提交出现问题，可以尝试调整「课程类型」选项。\n"
                    "请不要随意调整「课程类型」，不正确时，部分选项的评教结果可能出现异常"),
            self.questionnaireFrame
        )
        self.questionnaireFrameLayout.addWidget(self.noQuestionnaireLabel, alignment=Qt.AlignHCenter)
        self.questionnaireFrameLayout.addSpacing(20)
        self.questionnaireFrameLayout.addWidget(self.hintLabel, alignment=Qt.AlignHCenter)
        self.questionnaireFrameLayout.addSpacing(10)
        self.hintLabel.setVisible(False)

        self.startLabel = BodyLabel(self.tr("还没有评教信息"), self.startFrame)
        self.startButton = PrimaryPushButton(self.tr("获取评教问卷"), self.startFrame)
        self.startFrameLayout.addWidget(self.startLabel, alignment=Qt.AlignHCenter)
        self.startButton.setFixedWidth(150)
        self.startButton.clicked.connect(self.onStartButtonClicked)
        self.startFrameLayout.addWidget(self.startButton, alignment=Qt.AlignHCenter)

        self.vBoxLayout.addWidget(self.startFrame, 1, alignment=Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.questionnaireFrame, 1, alignment=Qt.AlignVCenter)

        StyleSheet.AUTO_JUDGE_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    @pyqtSlot()
    def onThreadStarted(self):
        self.processDialog.exec()

    @pyqtSlot()
    def onViewEhallTriggered(self):
        QDesktopServices.openUrl(QUrl("https://ehall.xjtu.edu.cn/"))

    def switchTo(self, item):
        if item == self.startFrame:
            self.startFrame.setVisible(True)
            self.questionnaireFrame.setVisible(False)
            self.hintLabel.setVisible(False)
        else:
            self.startFrame.setVisible(False)
            self.hintLabel.setVisible(True)
            self.questionnaireFrame.setVisible(True)

    def addQuestionnaire(self, questionnaire: Questionnaire, finished=False):
        widget = JudgeCard(questionnaire, self, finished, self.questionnaireFrame)
        if not finished:
            self.questionnaireWidgets.append(widget)
        else:
            self.finishedQuestionnaireWidgets.append(widget)
            if not self.showAllAction.isChecked():
                widget.setVisible(False)

        self.questionnaireFrameLayout.addWidget(widget)

    def clearWidgets(self):
        for widget in self.questionnaireWidgets:
            widget.deleteLater()
        for widget in self.finishedQuestionnaireWidgets:
            widget.deleteLater()

        self.questionnaireWidgets.clear()
        self.finishedQuestionnaireWidgets.clear()

    def setQuestionnaireFinished(self, widget: JudgeCard):
        widget.setFinished(True)
        self.finishedQuestionnaireWidgets.append(widget)
        self.questionnaireWidgets.remove(widget)
        # 重新排序问卷的位置
        self.questionnaireFrameLayout.removeWidget(widget)
        self.questionnaireFrameLayout.addWidget(widget)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        self.thread_.account = accounts.current
        self.clearWidgets()
        self.switchTo(self.startFrame)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        if self.window().isActiveWindow():
            InfoBar.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, isClosable=True, parent=self)

    @pyqtSlot()
    def onStartButtonClicked(self):
        self.clearWidgets()
        self.thread_.choice = JudgeChoice.GET_COURSES
        self.thread_.start()

    @pyqtSlot(bool)
    def onShowFinishedQuestionnairesTriggered(self, isChecked):
        if isChecked:
            self.showFinishedQuestionnaires(True)
        else:
            self.showFinishedQuestionnaires(False)

    def showFinishedQuestionnaires(self, status: bool):
        for widget in self.finishedQuestionnaireWidgets:
            widget.setVisible(status)

    @pyqtSlot()
    def onEditSuccess(self):
        questionnaire = self.thread_.questionnaire
        if self.window().isActiveWindow():
            InfoBar.success(self.tr("问卷编辑成功"), self.tr(f"{questionnaire.KCM} {questionnaire.BPJS} 编辑成功"),
                            duration=3000, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.success(self.tr("问卷编辑成功"), self.tr(f"{questionnaire.KCM} {questionnaire.BPJS} 编辑成功"),
                            duration=-1, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)

    @pyqtSlot()
    def onSubmitSuccess(self):
        questionnaire = self.thread_.questionnaire
        if self.window().isActiveWindow():
            InfoBar.success(self.tr("问卷提交成功"), self.tr(f"{questionnaire.KCM} {questionnaire.BPJS} 评教成功"),
                            duration=3000, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.success(self.tr("问卷提交成功"), self.tr(f"{questionnaire.KCM} {questionnaire.BPJS} 评教成功"),
                            duration=-1, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
        for one in self.questionnaireWidgets:
            if one.questionnaire == questionnaire:
                self.setQuestionnaireFinished(one)
                one.setVisible(self.showAllAction.isChecked())
                break

    @pyqtSlot(list, list)
    def onGetQuestionnaireFinish(self, questionnaires: list, finished_questionnaires: list):
        if len(questionnaires) == 0:
            self.noQuestionnaireLabel.setVisible(True)
        else:
            self.noQuestionnaireLabel.setVisible(False)

        for questionnaire in questionnaires:
            self.addQuestionnaire(questionnaire, False)
        self.questionnaireFrameLayout.addSpacing(20)
        for questionnaire in finished_questionnaires:
            self.addQuestionnaire(questionnaire, True)
        self.switchTo(self.questionnaireFrame)
