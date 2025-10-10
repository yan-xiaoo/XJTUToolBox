from typing import Union, Dict

from PyQt5.QtCore import Qt, pyqtSlot, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QFrame
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, ScrollArea, PrimaryPushButton, \
    InfoBar, InfoBarPosition, CommandBar, Action, FluentIcon, TitleLabel, MessageBox
from ehall import Questionnaire
from gste.judge import GraduateQuestionnaire, GraduateQuestionnaireData
from .GraduateJudgeOptionInterface import GraduateJudgeOptionMessageBox
from .JudgeOptionInterface import JudgeOptionMessageBox
from .JudgeAllOptionInterface import JudgeAllOptionMessageBox
from ..threads.GraduateJudgeThread import GraduateJudgeThread, GraduateJudgeChoice
from ..utils import StyleSheet
from ..threads.JudgeThread import JudgeThread, JudgeChoice
from ..threads.ProcessWidget import ProcessWidget
from ..utils import accounts


class JudgeCard(CardWidget):
    # 发送自身的 questionnaire 属性的内容
    judgeButtonClicked = pyqtSignal(object, bool)

    def __init__(self, questionnaire, title: str, description: str, interface: "AutoJudgeInterface", finished=False, parent=None):
        super().__init__(parent)

        # 用于修改线程信息
        self.thread_ = interface.thread_
        self.parent_ = interface
        self.finished = finished
        self.title = title
        self.questionnaire = questionnaire
        self.description = description

        if not finished:
            self.titleLabel = BodyLabel(title, self)
        else:
            self.titleLabel = BodyLabel(title + self.tr(" (已完成)"), self)
        self.contentLabel = CaptionLabel(description, self)
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
        self.judgeButtonClicked.emit(self.questionnaire, self.finished)

    def setFinished(self, status):
        self.finished = status
        if status:
            self.submitButton.setText(self.tr("编辑评教"))
            self.titleLabel.setText(self.title + self.tr(" (已完成)"))
        else:
            self.submitButton.setText(self.tr("开始评教"))
            self.titleLabel.setText(self.title)


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
        self.viewAction = Action(FluentIcon.LINK, self.tr("前往评教系统查看"), self.commandBar)
        self.viewAction.triggered.connect(self.onViewEhallTriggered)
        self.judgeAllAction = Action(FluentIcon.PLAY, self.tr("全部评教"), self.commandBar)
        self.judgeAllAction.triggered.connect(self.onJudgeAllButtonClicked)
        
        self.commandBar.addAction(self.refreshAction)
        self.commandBar.addAction(self.showAllAction)
        self.commandBar.addAction(self.viewAction)
        self.commandBar.addAction(self.judgeAllAction)
        self.commandBar.setMinimumWidth(500)
        self.vBoxLayout.addWidget(self.commandBar, 1, alignment=Qt.AlignTop | Qt.AlignHCenter)

        self.thread_ = JudgeThread(accounts.current, choice=JudgeChoice.GET_COURSES)
        self.thread_.questionnaires.connect(self.onGetQuestionnaireFinish)
        self.thread_.error.connect(self.onThreadError)
        self.thread_.submitSuccess.connect(self.onSubmitSuccess)
        self.thread_.editSuccess.connect(self.onEditSuccess)
        self.thread_.started.connect(self.onThreadStarted)
        self.thread_.finished.connect(self.unlockAllCards)

        self.gradateThread = GraduateJudgeThread(accounts.current, choice=GraduateJudgeChoice.GET_COURSES)
        self.gradateThread.started.connect(self.onGradateThreadStarted)
        self.gradateThread.error.connect(self.onThreadError)
        self.gradateThread.questionnaires.connect(self.onGetQuestionnaireFinish)
        self.gradateThread.questionnaireData.connect(self._onGetGraduateQuestionnaireData)
        self.gradateThread.finished.connect(self.unlockAllCards)
        self.gradateThread.submitSuccess.connect(self.onGraduateSubmitSuccess)

        self.processWidget = None
        self.graduateProcessWidget = None

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        self.startFrame = QFrame(self.view)
        self.startFrameLayout = QVBoxLayout(self.startFrame)
        self.questionnaireFrame = QFrame(self.view)
        self.questionnaireWidgets = []
        self.finishedQuestionnaireWidgets = []
        self.noQuestionnaireLabel = TitleLabel(self.tr("没有需要完成的问卷"), self.questionnaireFrame)
        self.noQuestionnaireLabel.setVisible(False)
        # 标识当前的界面
        self.currentFrame = self.startFrame

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

        # 初始化本科生/研究生不同的内容
        self.onCurrentAccountChanged()

    @pyqtSlot()
    def onThreadStarted(self):
        # 在使用前初始化进度条组件，否则会出现奇怪的问题
        if self.processWidget is None:
            self.processWidget = ProcessWidget(self.thread_, stoppable=True, hide_on_end=True)
            # 将组件插入在 Commandbar 后面，Frame 前面
            self.vBoxLayout.insertWidget(1, self.processWidget, alignment=Qt.AlignTop | Qt.AlignHCenter)

        self.processWidget.setVisible(True)

    @pyqtSlot()
    def onGradateThreadStarted(self):
        # 在使用前初始化进度条组件，否则会出现奇怪的问题
        if self.graduateProcessWidget is None:
            self.graduateProcessWidget = ProcessWidget(self.gradateThread, stoppable=True, hide_on_end=True)
            # 将组件插入在 Commandbar 后面，Frame 前面
            self.vBoxLayout.insertWidget(1, self.graduateProcessWidget, alignment=Qt.AlignTop | Qt.AlignHCenter)

        self.graduateProcessWidget.setVisible(True)

    @pyqtSlot()
    def onViewEhallTriggered(self):
        if accounts.current is not None and accounts.current.type == accounts.current.POSTGRADUATE:
            QDesktopServices.openUrl(QUrl("http://gste.xjtu.edu.cn/"))
        else:
            QDesktopServices.openUrl(QUrl("https://ehall.xjtu.edu.cn/"))

    def lockAllCards(self):
        for card in self.questionnaireWidgets:
            card.submitButton.setEnabled(False)
        for card in self.finishedQuestionnaireWidgets:
            card.submitButton.setEnabled(False)

    def unlockAllCards(self):
        for card in self.questionnaireWidgets:
            card.submitButton.setEnabled(True)
        for card in self.finishedQuestionnaireWidgets:
            card.submitButton.setEnabled(True)

    def switchTo(self, item):
        if item == self.startFrame:
            self.startFrame.setVisible(True)
            self.questionnaireFrame.setVisible(False)
            self.hintLabel.setVisible(False)
        else:
            self.startFrame.setVisible(False)
            self.hintLabel.setVisible(True)
            self.questionnaireFrame.setVisible(True)
        self.currentFrame = item

    @pyqtSlot(object, bool)
    def _onJudgeButtonClicked(self, questionnaire, finished):
        if accounts.current is not None:
            if accounts.current.type == accounts.current.UNDERGRADUATE:
                dev_interface = JudgeOptionMessageBox(questionnaire, self.thread_, finished, self)
                dev_interface.exec()
            else:
                # 研究生问卷需要获得问卷详细信息
                self.gradateThread.questionnaire = questionnaire
                self.gradateThread.choice = GraduateJudgeChoice.GET_DATA
                self.lockAllCards()
                self.gradateThread.start()
                self.graduateProcessWidget.setVisible(True)

    def addQuestionnaire(self, questionnaire: Union[Questionnaire, GraduateQuestionnaire], finished=False):
        if accounts.current.type == accounts.current.UNDERGRADUATE:
            title = f"{questionnaire.KCM} {questionnaire.BPJS}"
            description = f"{questionnaire.WJMC}"
        else:
            title = f"{questionnaire.KCMC} {questionnaire.JSXM}"
            description = f"{questionnaire.TERMNAME} {questionnaire.BJMC}"
        widget = JudgeCard(questionnaire, title, description, self, finished, self.questionnaireFrame)
        widget.judgeButtonClicked.connect(self._onJudgeButtonClicked)
        if not finished:
            self.questionnaireWidgets.append(widget)
        else:
            self.finishedQuestionnaireWidgets.append(widget)
            if not self.showAllAction.isChecked():
                widget.setVisible(False)

        self.questionnaireFrameLayout.addWidget(widget)

    @pyqtSlot(GraduateQuestionnaireData)
    def _onGetGraduateQuestionnaireData(self, questionnaire: GraduateQuestionnaireData):
        origin = self.gradateThread.questionnaire
        dev_interface = GraduateJudgeOptionMessageBox(origin.KCMC + " " + origin.JSXM, questionnaire, self)
        if dev_interface.exec():
            if self.gradateThread.questionnaire is None:
                self.onThreadError("", self.tr("内部错误：未找到正在评教的问卷"))
            else:
                # 进行评教
                self.gradateThread.choice = GraduateJudgeChoice.JUDGE
                self.gradateThread.questionnaire_data = questionnaire
                self.gradateThread.score = dev_interface.interface.currentLevel()
                self.gradateThread.answer_dict = dev_interface.interface.textsByQuestionId()
                self.gradateThread.start()
                self.graduateProcessWidget.setVisible(True)

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
        if accounts.current is None:
            self.onThreadError(self.tr("未登录"), self.tr("请先添加一个账号"))
            return

        if accounts.current is not None and accounts.current.type == accounts.current.POSTGRADUATE:
            # 研究生评教系统是需要 WebVPN 的。如果没有登录的话，询问用户想要怎么登录。
            if not self.gradateThread.session.has_login:
                w = MessageBox(self.tr("开始评教"), self.tr("您想使用什么方式登录评教系统？"),
                               self)
                w.yesButton.setText(self.tr("WebVPN 登录"))
                w.cancelButton.setText(self.tr("直接登录"))
                if w.exec():
                    self.gradateThread.session.login_method = self.gradateThread.session.LoginMethod.WEBVPN
                else:
                    self.gradateThread.session.login_method = self.gradateThread.session.LoginMethod.NORMAL

            self.gradateThread.choice = GraduateJudgeChoice.GET_COURSES
            self.gradateThread.start()
        else:
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
    def onJudgeAllButtonClicked(self):
        if accounts.current is not None and accounts.current.type == accounts.current.POSTGRADUATE:
            # 研究生暂时不支持
            self.onThreadError("", self.tr("抱歉，由于问卷题目可能不同，研究生暂时不支持一键评教"))
            return

        # 先检查是否有待评教的课程
        if len(self.questionnaireWidgets) == 0:
            if self.currentFrame == self.questionnaireFrame:
                if len(self.finishedQuestionnaireWidgets) > 0:
                    self.onThreadError("没有待评教课程", "所有课程均已评教完成")
                else:
                    self.onThreadError("没有待评教课程", "似乎没有需要评教的课程")
            else:
                self.onThreadError("没有待评教课程", "请先刷新获取评教问卷")
            return

        dev_interface = JudgeAllOptionMessageBox(self.thread_, self)
        dev_interface.exec()

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

    @pyqtSlot()
    def onGraduateSubmitSuccess(self):
        questionnaire = self.gradateThread.questionnaire
        if self.window().isActiveWindow():
            InfoBar.success(self.tr("问卷提交成功"), self.tr(f"{questionnaire.KCMC} {questionnaire.JSXM} 评教成功"),
                            duration=3000, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.success(self.tr("问卷提交成功"), self.tr(f"{questionnaire.KCMC} {questionnaire.JSXM} 评教成功"),
                            duration=-1, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
        for one in self.questionnaireWidgets:
            if one.questionnaire == questionnaire:
                self.setQuestionnaireFinished(one)
                one.setVisible(self.showAllAction.isChecked())
                break

    @pyqtSlot()
    def onSubmitSuccess(self):
        # 处理单个课程提交成功的情况
        if self.thread_.choice == JudgeChoice.JUDGE:
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
        # 处理所有课程评价完成的情况
        elif self.thread_.choice == JudgeChoice.JUDGE_ALL:
            # 刷新列表以显示最新状态
            self.onStartButtonClicked()
            if self.window().isActiveWindow():
                InfoBar.success(self.tr("自动评价完成"), self.tr("所有课程评教已完成"),
                                duration=3000, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
            else:
                InfoBar.success(self.tr("自动评价完成"), self.tr("所有课程评教已完成"),
                                duration=-1, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)