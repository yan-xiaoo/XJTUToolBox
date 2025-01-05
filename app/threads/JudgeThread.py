import requests
from PyQt5.QtCore import pyqtSignal

from .ProcessWidget import ProcessThread
from ..sessions.ehall_session import EhallSession
from ..utils import Account, logger

from ehall import AutoJudge
from auth import Login, EHALL_LOGIN_URL, ServerError
from enum import Enum


class JudgeChoice(Enum):
    # 获得所有待评教的课程
    GET_COURSES = 0
    # 评教
    JUDGE = 1
    # 编辑并重新提交问卷
    EDIT = 2


class JudgeThread(ProcessThread):
    # 未完成问卷与已完成问卷
    questionnaires = pyqtSignal(list, list)
    submitSuccess = pyqtSignal()
    editSuccess = pyqtSignal()

    def __init__(self, account: Account, choice: JudgeChoice, parent=None):
        super().__init__(parent)
        self.account = account
        self.choice = choice
        self.judge_ = None
        self.questionnaire = None
        self.template = None

    @property
    def session(self) -> EhallSession:
        """
        获取当前账户用于访问 ehall 的 session
        """
        return self.account.session_manager.get_session("ehall")

    def login(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在登录 EHALL..."))
        self.progressChanged.emit(10)
        login = Login(EHALL_LOGIN_URL, session=self.session)
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login(self.account.username, self.account.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)
        self.messageChanged.emit(self.tr("正在完成登录..."))
        login.post_login()
        self.progressChanged.emit(88)

        self.session.has_login = True

        # 进入评教区域
        self.messageChanged.emit(self.tr("正在进入评教系统..."))
        self.judge_ = AutoJudge(self.session)
        self.progressChanged.emit(100)

        return True

    def judge(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在评教..."))
        self.progressChanged.emit(20)
        data = self.judge_.questionnaireData(self.questionnaire, self.account.username)
        self.progressChanged.emit(40)
        if not self.can_run:
            return False
        options = self.judge_.questionnaireOptions(self.questionnaire, self.account.username)
        self.progressChanged.emit(60)
        if not self.can_run:
            return False
        for one_data in data:
            self.template.complete(one_data, options, True)
        if not self.can_run:
            return False
        self.progressChanged.emit(80)
        result, msg = self.judge_.submitQuestionnaire(self.questionnaire, data)
        self.progressChanged.emit(100)
        if not result:
            self.error.emit("提交失败", msg)
            return False
        return True

    def edit(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在重新评教..."))
        self.progressChanged.emit(5)
        result, msg = self.judge_.editQuestionnaire(self.questionnaire, self.account.username)
        if not result:
            self.error.emit("编辑失败", msg)
            return False
        self.progressChanged.emit(20)
        data = self.judge_.questionnaireData(self.questionnaire, self.account.username)
        self.progressChanged.emit(40)
        if not self.can_run:
            return False
        options = self.judge_.questionnaireOptions(self.questionnaire, self.account.username)
        self.progressChanged.emit(60)
        if not self.can_run:
            return False
        for one_data in data:
            self.template.complete(one_data, options, True)
        if not self.can_run:
            return False
        self.progressChanged.emit(80)
        result, msg = self.judge_.submitQuestionnaire(self.questionnaire, data)
        self.progressChanged.emit(100)
        if not result:
            self.error.emit("提交失败", msg)
            return False
        return True

    def run(self):
        # 强制重置可运行状态，避免上次取消后本次直接退出
        self.can_run = True
        if self.account is None:
            self.error.emit(self.tr("未登录"), self.tr("请您先添加一个账户"))
            self.canceled.emit()
            return
        # 依据当前的 session 重建 judge 对象
        if self.session.has_login:
            self.judge_ = AutoJudge(self.session)
        self.progressChanged.emit(0)
        try:
            if self.choice == JudgeChoice.GET_COURSES:
                if not self.session.has_login:
                    result = self.login()
                    if not result:
                        self.canceled.emit()
                        return

                self.messageChanged.emit(self.tr("正在获取未完成问卷信息..."))
                self.progressChanged.emit(66)
                if not self.can_run:
                    self.canceled.emit()
                    return
                questionnaires = self.judge_.unfinishedQuestionnaires()
                self.progressChanged.emit(88)
                self.messageChanged.emit(self.tr("正在获取已完成问卷信息..."))
                questionnaires_finished = self.judge_.finishedQuestionnaires()
                self.progressChanged.emit(100)
                self.questionnaires.emit(questionnaires, questionnaires_finished)
                self.hasFinished.emit()
            elif self.choice == JudgeChoice.JUDGE:
                if not self.session.has_login:
                    result = self.login()
                    if not result:
                        self.canceled.emit()
                        return
                result = self.judge()
                if not result:
                    self.canceled.emit()
                    return
                self.submitSuccess.emit()
                self.hasFinished.emit()
            elif self.choice == JudgeChoice.EDIT:
                if not self.session.has_login:
                    result = self.login()
                    if not result:
                        self.canceled.emit()
                        return
                result = self.edit()
                if not result:
                    self.canceled.emit()
                    return
                self.editSuccess.emit()
                self.hasFinished.emit()
            else:
                raise ValueError(self.tr("未知选项"))
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            self.error.emit(self.tr("服务器错误"), str(e))
            self.canceled.emit()
        except requests.ConnectionError:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("无网络连接"), self.tr("请检查网络连接，然后重试。"))
            self.canceled.emit()
        except requests.RequestException as e:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("网络错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
