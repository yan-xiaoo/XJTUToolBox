from typing import Optional

import requests
from PyQt5.QtCore import pyqtSignal

from auth.new_login import NewLogin
from .ProcessWidget import ProcessThread
from ..sessions.ehall_session import EhallSession
from ..utils import Account, logger, cfg, accounts

from ehall import AutoJudge, QuestionnaireTemplate
from auth import EHALL_LOGIN_URL, ServerError
from enum import Enum


class JudgeChoice(Enum):
    # 获得所有待评教的课程
    GET_COURSES = 0
    # 评教
    JUDGE = 1
    # 编辑并重新提交问卷
    EDIT = 2
    # 自动评价所有课程
    JUDGE_ALL = 3


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
        self.score: int = 100
        self.msgAll: str = ""    # 自定义评语
        self.scoreAll: Optional[QuestionnaireTemplate.Score] = None

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
        # 防止重复登录
        self.session.cookies.clear()
        login = NewLogin(EHALL_LOGIN_URL, session=self.session, visitor_id=str(cfg.loginId.value))
        self.messageChanged.emit(self.tr("正在验证身份..."))
        self.progressChanged.emit(33)
        if not self.can_run:
            return False
        login.login_or_raise(self.account.username, self.account.password)
        if not self.can_run:
            return False
        self.progressChanged.emit(66)
        self.messageChanged.emit(self.tr("正在完成登录..."))
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
            self.template.complete(one_data, options, True, default_score=self.score, default_subjective=self.msgAll)
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
            self.template.complete(one_data, options, True, default_score=self.score, default_subjective=self.msgAll)
        if not self.can_run:
            return False
        self.progressChanged.emit(80)
        result, msg = self.judge_.submitQuestionnaire(self.questionnaire, data)
        self.progressChanged.emit(100)
        if not result:
            self.error.emit("提交失败", msg)
            return False
        return True

    def judge_all(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在获取所有待评教课程..."))
        self.progressChanged.emit(10)
        questionnaires = self.judge_.unfinishedQuestionnaires()
        
        if not questionnaires:
            self.error.emit("没有待评教课程", "所有课程已经完成评教")
            return False
        
        total_count = len(questionnaires)
        success_count = 0
        
        for i, questionnaire in enumerate(questionnaires):
            if not self.can_run:
                return False
                
            progress_base = 10 + (i * 90 // total_count)
            
            try:
                self.messageChanged.emit(self.tr(f"正在评教第{i+1}/{total_count}门: {questionnaire.KCM}"))
                self.progressChanged.emit(progress_base + 5)
                data = self.judge_.questionnaireData(questionnaire, self.account.username)
                self.progressChanged.emit(progress_base + 20)
                
                options = self.judge_.questionnaireOptions(questionnaire, self.account.username)
                self.progressChanged.emit(progress_base + 40)
                
                # 获取模版
                type_dict = {
                    QuestionnaireTemplate.Type.THEORY: "理论课",
                    QuestionnaireTemplate.Type.IDEOLOGY: "思政课",
                    QuestionnaireTemplate.Type.GENERAL: "通识课",
                    QuestionnaireTemplate.Type.EXPERIMENT: "实验课",
                    QuestionnaireTemplate.Type.PROJECT: "项目设计课",
                    QuestionnaireTemplate.Type.PHYSICAL: "体育课"
                }

                questionnaire_type = None
                for item in type_dict:
                    if type_dict[item] in questionnaire.WJMC:
                        questionnaire_type = item
                        break
                if questionnaire_type is None:
                    # 默认理论课
                    questionnaire_type = QuestionnaireTemplate.Type.THEORY

                template = QuestionnaireTemplate.from_file(
                    questionnaire_type,
                    self.scoreAll
                )

                for one_data in template.data:
                    if one_data.TXDM != '01':
                        one_data.ZGDA = self.msgAll if self.msgAll else self.tr("无")

                for one_data in data:
                    template.complete(one_data, options, True, default_score=QuestionnaireTemplate.score_to_int(self.scoreAll), default_subjective=self.msgAll)
                self.progressChanged.emit(progress_base + 60)
                
                result, msg = self.judge_.submitQuestionnaire(questionnaire, data)
                self.progressChanged.emit(progress_base + 80)
                
                if result:
                    success_count += 1
                    self.messageChanged.emit(self.tr(f"第{i+1}/{total_count}门课程评教成功: {questionnaire.KCM}"))
                else:
                    self.messageChanged.emit(self.tr(f"第{i+1}/{total_count}门课程评教失败: {questionnaire.KCM}"))
                    logger.warning(f"评教失败: {msg}")
                
            except Exception as e:
                self.messageChanged.emit(self.tr(f"第{i+1}/{total_count}门课程评教异常: {questionnaire.KCM}"))
                logger.error(f"评教异常: {questionnaire.KCM} {str(e)}")
                
            self.progressChanged.emit(progress_base + 90)

        if success_count != total_count:
            self.error.emit("", self.tr(f"所有评教完成，成功{success_count}/{total_count}门"))

        self.progressChanged.emit(100)
        return success_count > 0

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
            elif self.choice == JudgeChoice.JUDGE_ALL:
                if not self.session.has_login:
                    result = self.login()
                    if not result:
                        self.canceled.emit()
                        return
                result = self.judge_all()
                if not result:
                    self.canceled.emit()
                    return
                self.submitSuccess.emit()
                self.hasFinished.emit()
            else:
                raise ValueError(self.tr("未知选项"))
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            if e.code == 102:
                self.error.emit(self.tr("登录问题"), self.tr("需要进行两步验证，请前往账户界面，选择对应账户进行验证。"))
                accounts.current.MFASignal.emit(True)
            else:
                self.error.emit(self.tr("服务器错误"), e.message)
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