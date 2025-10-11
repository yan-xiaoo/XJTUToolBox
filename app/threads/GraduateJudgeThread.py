from typing import Optional, Dict

import requests
from PyQt5.QtCore import pyqtSignal

from gmis.lesson_detail import GraduateLessonDetail
from gmis.score import GraduateScore
from gste.judge import GraduateAutoJudge, GraduateQuestionnaire, GraduateQuestionnaireData
from .ProcessWidget import ProcessThread
from ..sessions.gmis_session import GMISSession
from ..sessions.gste_session import GSTESession
from ..utils import Account, logger, accounts

from auth import ServerError
from enum import Enum


class GraduateJudgeChoice(Enum):
    # 获得所有待评教的课程
    GET_COURSES = 0
    # 获得问卷数据
    GET_DATA = 1
    # 评教
    JUDGE = 2
    # 全部评教
    JUDGE_ALL = 3


class GraduateJudgeThread(ProcessThread):
    # 未完成问卷与已完成问卷
    questionnaires = pyqtSignal(list, list)
    # 单个问卷的数据
    questionnaireData = pyqtSignal(GraduateQuestionnaireData)
    submitSuccess = pyqtSignal()
    editSuccess = pyqtSignal()
    allSubmitSuccess = pyqtSignal()

    def __init__(self, account: Account, choice: GraduateJudgeChoice, parent=None):
        super().__init__(parent)
        self.account = account
        self.choice = choice
        # 待评教问卷，在 JudgeChoice 为 GET_DATA 和 JUDGE 时需要设置
        self.questionnaire: Optional[GraduateQuestionnaire] = None
        # 待评教问卷的数据（答案），在 JudgeChoice 为 JUDGE 时需要设置
        self.questionnaire_data: Optional[GraduateQuestionnaireData] = None
        # 问卷的选择题等级（3:优，2:良，1:合格，0:不合格）。由于系统要求，选项不能全优，选择 3 时会将随机一个题目填写为良。
        self.score: int = 3
        # 问卷的主观题答案，字典，题目 ID->回答
        self.answer_dict: Optional[Dict[str, str]] = None
        # 单个通用主观题答案
        self.single_answer: str = "无"

    def set_login_method(self, method: GSTESession.LoginMethod):
        """
        设置登录方式，仅在当前 session 未登录时生效
        """
        if not self.session.has_login:
            self.session.login_method = method

    @property
    def session(self) -> GSTESession:
        """
        获取当前账户用于访问研究生评教系统的 session
        """
        return self.account.session_manager.get_session("gste")

    @property
    def gmis_session(self) -> GMISSession:
        """
        获得当前账户用于访问研究生管理信息系统的 session
        """
        return self.account.session_manager.get_session("gmis")

    def webvpn_login(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在通过 WebVPN 登录评教系统..."))
        self.session.webvpn_login(self.account.username, self.account.password)
        self.messageChanged.emit(self.tr("登录 WebVPN 成功。"))

    def normal_login(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在直接登录评教系统..."))
        self.session.login(self.account.username, self.account.password)
        self.messageChanged.emit(self.tr("直接登录评教系统成功。"))

    def run(self):
        # 强制重置可运行状态，避免上次取消后本次直接退出
        self.can_run = True
        if self.account is None:
            self.error.emit(self.tr("未登录"), self.tr("请您先添加一个账户"))
            self.canceled.emit()
            return

        self.progressChanged.emit(0)
        try:
            # 如果当前账户已经登录，重建代理对象，防止出现 util 和 session 不对应的情况。
            if self.session.has_login:
                # 如果当前 session 已经登录，必须沿用当前登录方式。
                util = GraduateAutoJudge(self.session, use_webvpn=self.session.login_method == self.session.LoginMethod.WEBVPN)
            else:
                # 手动登录。
                if self.session.login_method == self.session.LoginMethod.NORMAL:
                    self.normal_login()
                else:
                    self.webvpn_login()
                # 登录之后改一下进度条样式
                self.setIndeterminate.emit(False)
                self.progressChanged.emit(0)
                util = GraduateAutoJudge(self.session, use_webvpn=self.session.login_method == self.session.LoginMethod.WEBVPN)
                if not self.can_run:
                    self.canceled.emit()
                    return
            # 到此为止，一定已经完成了登录
            if not self.can_run:
                self.canceled.emit()
                return

            if self.choice == GraduateJudgeChoice.GET_COURSES:
                self.messageChanged.emit(self.tr("正在获取问卷信息..."))
                self.progressChanged.emit(50)
                questionnaires = util.getQuestionnaires()
                # 是否完成由 assessment 字段区分
                unfinished = [one for one in questionnaires if one.ASSESSMENT == "allow"]
                finished = [one for one in questionnaires if one.ASSESSMENT == "already"]
                # 剩下的不知道是什么（目前也没遇到过），不处理
                self.progressChanged.emit(100)
                self.questionnaires.emit(unfinished, finished)
                self.hasFinished.emit()
            elif self.choice == GraduateJudgeChoice.GET_DATA:
                if self.questionnaire is None:
                    self.error.emit("", "错误：没有需要获得数据的设置问卷")
                    self.canceled.emit()
                    return
                self.progressChanged.emit(50)
                self.messageChanged.emit(self.tr("正在获得问卷题目..."))
                data = util.getQuestionnaireData(questionnaire=self.questionnaire)
                self.questionnaireData.emit(data)
                self.hasFinished.emit()
            elif self.choice == GraduateJudgeChoice.JUDGE:
                if self.questionnaire is None:
                    self.error.emit("", "错误：没有需要评教的设置问卷")
                    self.canceled.emit()
                    return
                if self.questionnaire_data is None:
                    self.error.emit("", "错误：没有需要评教的设置问卷数据")
                    self.canceled.emit()
                    return

                # 开填！
                # 首先，填写基本信息
                self.progressChanged.emit(30)
                if not self.gmis_session.has_login:
                    self.messageChanged.emit(self.tr("正在登录研究生管理信息系统..."))
                    self.gmis_session.login(self.account.username, self.account.password)

                if not self.can_run:
                    self.canceled.emit()
                    return
                # 我们需要从 GMIS 拉取课程的教材、授课语言等信息（因为问卷中要求填写这些内容）
                self.progressChanged.emit(50)
                self.messageChanged.emit(self.tr("正在获得课程基本信息..."))
                gmis_util = GraduateLessonDetail(self.gmis_session)
                basic_info = gmis_util.lesson_detail(self.questionnaire.KCBH)

                if not self.can_run:
                    self.canceled.emit()
                    return

                self.progressChanged.emit(70)
                self.messageChanged.emit(self.tr("正在获得课程类型信息..."))
                score_util = GraduateScore(self.gmis_session)
                all_courses = score_util.all_course_info()
                for lesson in all_courses:
                    if lesson["courseName"] == self.questionnaire.KCMC:
                        if lesson["type"] == "学位课程":
                            is_main_course = True
                        else:
                            is_main_course = False
                        break
                else:
                    # 没有信息默认为选修课
                    is_main_course = False
                # 填写问卷
                util.completeQuestionnaire(self.questionnaire, self.questionnaire_data, basic_info, self.score, self.answer_dict, is_main_course)

                self.progressChanged.emit(90)
                self.messageChanged.emit(self.tr("正在提交问卷..."))
                util.submitQuestionnaire(self.questionnaire, self.questionnaire_data)
                self.submitSuccess.emit()
                self.hasFinished.emit()
            elif self.choice == GraduateJudgeChoice.JUDGE_ALL:
                # 评教全部课程
                # 先获得公用内容：登录 GMIS 和获得课程类型信息
                self.progressChanged.emit(5)
                if not self.gmis_session.has_login:
                    self.messageChanged.emit(self.tr("正在登录研究生管理信息系统..."))
                    self.gmis_session.login(self.account.username, self.account.password)
                gmis_util = GraduateLessonDetail(self.gmis_session)

                if not self.can_run:
                    self.canceled.emit()
                    return

                self.progressChanged.emit(10)
                self.messageChanged.emit(self.tr("正在获得全部课程类型信息..."))
                score_util = GraduateScore(self.gmis_session)
                all_courses = score_util.all_course_info()

                if not self.can_run:
                    self.canceled.emit()
                    return

                # 获得所有未完成问卷评教
                self.progressChanged.emit(15)
                self.messageChanged.emit(self.tr("正在获取全部问卷信息..."))
                all_questionnaires = util.getQuestionnaires()
                all_questionnaires = [one for one in all_questionnaires if one.ASSESSMENT == "allow"]

                step = 0
                for questionnaire in all_questionnaires:
                    step += 1
                    # 计算当前进度
                    self.progressChanged.emit(15 + int(85 * step / (len(all_questionnaires) * 3)))
                    # 获得问卷内容
                    self.messageChanged.emit(self.tr("正在获得 ") + questionnaire.KCMC + "-" + questionnaire.JSXM + self.tr(" 问卷的内容..."))
                    data = util.getQuestionnaireData(questionnaire=questionnaire)

                    if not self.can_run:
                        self.canceled.emit()
                        return

                    step += 1
                    # 获得课程基本信息
                    self.progressChanged.emit(15 + int(85 * step / (len(all_questionnaires) * 3)))
                    self.messageChanged.emit(self.tr("正在获得 ") + questionnaire.KCMC + self.tr(" 课程的基本信息..."))
                    basic_info = gmis_util.lesson_detail(questionnaire.KCBH)

                    if not self.can_run:
                        self.canceled.emit()
                        return

                    # 判断是否为学位课程
                    for lesson in all_courses:
                        if lesson["courseName"] == questionnaire.KCMC:
                            if lesson["type"] == "学位课程":
                                is_main_course = True
                            else:
                                is_main_course = False
                            break
                    else:
                        is_main_course = False

                    step += 1
                    # 评教
                    # 先设置所有主观题为同一内容
                    data.set_all_textarea(self.single_answer)
                    # 再完成问卷
                    util.completeQuestionnaire(questionnaire, data, basic_info, self.score, self.answer_dict, is_main_course)
                    self.progressChanged.emit(15 + int(85 * step / (len(all_questionnaires) * 3)))
                    self.messageChanged.emit(self.tr("正在提交 ") + questionnaire.KCMC + "-" + questionnaire.JSXM + self.tr(" 问卷..."))
                    util.submitQuestionnaire(questionnaire, data)

                    if not self.can_run:
                        self.canceled.emit()
                        return

                self.allSubmitSuccess.emit()

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