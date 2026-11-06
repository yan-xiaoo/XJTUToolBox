from typing import Union, Dict

from PyQt5.QtCore import Qt, pyqtSlot, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QFrame
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, ScrollArea, PrimaryPushButton, \
    InfoBar, InfoBarPosition, CommandBar, Action, FluentIcon, TitleLabel
from auth import getVPNUrl
from app.sessions.session_backend import AccessMode
from app.sessions.qms_session import QMSSession
from .JudgeOptionInterface import JudgeOptionMessageBox
from .JudgeAllOptionInterface import JudgeAllOptionMessageBox
from ..utils import StyleSheet
from ..threads.JudgeThread import JudgeThread, JudgeChoice
from ..threads.ProcessWidget import ProcessWidget
from ..utils import accounts
from qms import QMSQuestionnaire, QMS_TASKS_URL




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
        self._refresh_after_finished = False
        self.thread_.questionnaires.connect(self.onGetQuestionnaireFinish)
        self.thread_.error.connect(self.onThreadError)
        self.thread_.submitSuccess.connect(self.onSubmitSuccess)
        self.thread_.editSuccess.connect(self.onEditSuccess)

        self.processWidget = ProcessWidget(
            self.thread_, self.view, stoppable=True, hide_on_end=True
        )
        # Let the progress widget finish the old run before starting a refresh.
        self.thread_.finished.connect(self.onThreadFinished)
        self.processWidget.setVisible(False)
        self.vBoxLayout.addWidget(self.processWidget, alignment=Qt.AlignHCenter)

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
                    "评语会填入所有简答题；若留空将自动填写默认评语。\n"
                    "完成提交后可在 QMS 官网核对结果。"),
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
    def onViewEhallTriggered(self):
        self._open_campus_url(QMS_TASKS_URL, QMSSession)

    def _open_campus_url(self, url: str, site: type[QMSSession]) -> None:
        """根据当前访问策略打开评教系统链接。"""
        if accounts.current is not None:
            try:
                access_mode = accounts.current.session_manager.resolve_cached_access_mode_for_site(site)
                if access_mode == AccessMode.WEBVPN:
                    url = getVPNUrl(url)
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl(url))

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
            dev_interface = JudgeOptionMessageBox(questionnaire, self.thread_, finished, self)
            dev_interface.exec()

    def addQuestionnaire(self, questionnaire: QMSQuestionnaire, finished=False):
        widget = JudgeCard(
            questionnaire,
            questionnaire.display_title,
            questionnaire.display_description,
            self,
            finished,
            self.questionnaireFrame,
        )
        widget.judgeButtonClicked.connect(self._onJudgeButtonClicked)
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
        self._refresh_after_finished = False
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
        if self.thread_.isRunning():
            return
        if accounts.current is None:
            self.onThreadError(self.tr("未登录"), self.tr("请先添加一个账号"))
            return
        self.thread_.choice = JudgeChoice.GET_COURSES
        self.lockAllCards()
        self.processWidget.setVisible(True)
        self.thread_.start()

    @pyqtSlot()
    def onThreadFinished(self):
        self.unlockAllCards()
        if self._refresh_after_finished:
            self._refresh_after_finished = False
            self.onStartButtonClicked()

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
        if dev_interface.exec():
            self.thread_.msgAll = dev_interface.getText()
            self.thread_.scoreAll = dev_interface.getScore()
            self.thread_.choice = JudgeChoice.JUDGE_ALL
            self.processWidget.setVisible(True)
            self.thread_.start()

    @pyqtSlot(list, list)
    def onGetQuestionnaireFinish(self, questionnaires: list, finished_questionnaires: list):
        self.clearWidgets()
        if len(questionnaires) == 0:
            self.noQuestionnaireLabel.setVisible(True)
        else:
            self.noQuestionnaireLabel.setVisible(False)

        for questionnaire in questionnaires:
            self.addQuestionnaire(questionnaire, False)
        self.questionnaireFrameLayout.addSpacing(20)
        for questionnaire in finished_questionnaires:
            self.addQuestionnaire(questionnaire, True)
        if self.thread_.isRunning():
            self.lockAllCards()
        self.switchTo(self.questionnaireFrame)

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
            self._refresh_after_finished = True
            if self.window().isActiveWindow():
                InfoBar.success(self.tr("自动评价完成"), self.tr("所有课程评教已完成"),
                                duration=3000, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
            else:
                InfoBar.success(self.tr("自动评价完成"), self.tr("所有课程评教已完成"),
                                duration=-1, isClosable=True, position=InfoBarPosition.TOP_RIGHT, parent=self)
