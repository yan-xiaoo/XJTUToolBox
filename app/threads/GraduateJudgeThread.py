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


class GraduateJudgeThread(ProcessThread):
    # 未完成问卷与已完成问卷
    questionnaires = pyqtSignal(list, list)
    # 单个问卷的数据
    questionnaireData = pyqtSignal(GraduateQuestionnaireData)
    submitSuccess = pyqtSignal()
    editSuccess = pyqtSignal()

    def __init__(self, account: Account, choice: GraduateJudgeChoice, parent=None):
        super().__init__(parent)
        self.account = account
        self.choice = choice
        # 待评教问卷，在 JudgeChoice 为 GET_DATA 之后的内容时需要设置
        self.questionnaire: Optional[GraduateQuestionnaire] = None
        # 待评教问卷的数据（答案），在 JudgeChoice 为 JUDGE 之后的内容时需要设置
        self.questionnaire_data: Optional[GraduateQuestionnaireData] = None
        # 问卷的选择题等级（3:优，2:良，1:合格，0:不合格）。由于系统要求，选项不能全优，选择 3 时会将随机一个题目填写为良。
        self.score: int = 3
        # 问卷的主观题答案，字典，题目 ID->回答
        self.answer_dict: Optional[Dict[str, str]] = None

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

                # 开始填写基本信息
                self.questionnaire_data.set_answer_by_name("课程名称", self.questionnaire.KCMC)
                self.questionnaire_data.set_answer_by_name("上课教师", self.questionnaire.JSXM)
                if basic_info["课程教材"] and basic_info["课程教材"][0]["教程名称"] != "无指定书籍":
                    book_name: str = basic_info["课程教材"][0]["教程名称"]
                    if "自编讲义" in book_name:
                        # 1: 自编讲义的 ID
                        self.questionnaire_data.set_answer_by_name("教材情况", "1")
                    else:
                        # 2: 有教材选项的 ID
                        self.questionnaire_data.set_answer_by_name("教材情况", "2")
                    self.questionnaire_data.set_answer_by_name("教材名称", book_name)
                    # 用教材名称判断教材的语言（
                    self.questionnaire_data.set_answer_by_name("教材使用语言", "英文" if book_name.isascii() else "中文")
                else:
                    # 0: 无教材或讲义的 ID
                    self.questionnaire_data.set_answer_by_name("教材情况", "0")
                    # 很不幸的是，你还是得填教材名称和语言，不然过不了检测
                    self.questionnaire_data.set_answer_by_name("教材名称", "无")
                    self.questionnaire_data.set_answer_by_name("教材使用语言", "无教材")

                language = basic_info["授课语言"].strip("授课")
                if language == "全中文":
                    language = "中文"
                if language not in ("全英文", "中英文", "中文"):
                    language = "其他"
                self.questionnaire_data.set_answer_by_name("授课语言", language)
                # 填写课程类型信息（学位课或者选修课）
                self.progressChanged.emit(70)
                self.messageChanged.emit(self.tr("正在获得课程类型信息..."))
                score_util = GraduateScore(self.gmis_session)
                info = score_util.all_course_info()

                if not self.can_run:
                    self.canceled.emit()
                    return

                for lesson in info:
                    if lesson["courseName"] == self.questionnaire.KCMC:
                        if lesson["type"] == "学位课程":
                            self.questionnaire_data.set_answer_by_name("选修情况", "学位课")
                        else:
                            self.questionnaire_data.set_answer_by_name("选修情况", "选修课")
                        break
                else:
                    # 没找到课程，可能是新课，默认选修课
                    self.questionnaire_data.set_answer_by_name("选修情况", "选修课")
                # 填写所有选择题和填空题
                for question in self.questionnaire_data.questions:
                    # 防止覆盖上面填的
                    if question.view == "radio" and self.questionnaire_data.answers.get(question.id) is None:
                        self.questionnaire_data.set_answer_by_id(question.id, value=("不合格", "合格", "良好", "优秀")[min(self.score, 3)])
                    # 填空题处理
                    if question.view == "textarea":
                        if question.id in self.answer_dict:
                            self.questionnaire_data.set_answer_by_id(question.id, self.answer_dict[question.id] or "无")
                        elif question.name in self.answer_dict:
                            self.questionnaire_data.set_answer_by_id(question.id, self.answer_dict[question.name] or "无")
                        else:
                            # 如果真的找不到填空题答案，用“无”填。
                            self.questionnaire_data.set_answer_by_id(question.id, "无")

                # 系统要求不能全是良好
                if self.score >= 3:
                    for question in self.questionnaire_data.questions:
                        # 把第一个选项中包含”优秀“的选择题答案改成”良好“
                        if question.view == "radio" and question.options and question.options[0].get("value") == "优秀":
                            self.questionnaire_data.set_answer_by_id(question.id, "良好")
                            break

                self.progressChanged.emit(90)
                self.messageChanged.emit(self.tr("正在提交问卷..."))
                util.submitQuestionnaire(self.questionnaire, self.questionnaire_data)
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