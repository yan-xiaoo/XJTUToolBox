import time

from PyQt5.QtCore import pyqtSignal

from .ProcessWidget import ProcessThread
from ..utils import Account

from ehall import AutoJudge
from auth import Login, EHALL_LOGIN_URL
from enum import Enum
import traceback


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
        self.session = None
        self.expire_duration = 600
        self.judge_ = None
        self.questionnaire = None
        self.template = None
        # 开始时默认为过期状态，以便在实际使用时刷新
        self.expire_time = time.time() - self.expire_duration

    def login(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在登录 EHALL..."))
        self.progressChanged.emit(10)
        login = Login(EHALL_LOGIN_URL)
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login(self.account.username, self.account.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)
        self.messageChanged.emit(self.tr("正在完成登录..."))
        self.session = login.post_login()
        self.progressChanged.emit(88)

        # 进入评教区域
        self.messageChanged.emit(self.tr("正在进入评教系统..."))
        self.judge_ = AutoJudge(self.session)
        self.progressChanged.emit(100)

        self.expire_time = time.time()
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

    def has_expired(self):
        return time.time() - self.expire_time > self.expire_duration

    def set_expired(self):
        self.expire_time = time.time() - self.expire_duration

    def run(self):
        # 强制重置可运行状态，避免上次取消后本次直接退出
        self.can_run = True
        if self.account is None:
            self.error.emit(self.tr("未登录"), self.tr("请您先添加一个账户"))
            self.canceled.emit()
            return

        self.progressChanged.emit(0)
        try:
            if self.choice == JudgeChoice.GET_COURSES:
                if self.session is None or self.judge is None or self.has_expired():
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
                if self.session is None or self.judge_ is None or self.has_expired():
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
                if self.session is None or self.judge_ is None or self.has_expired():
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
        except Exception as e:
            traceback.print_exc()
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
