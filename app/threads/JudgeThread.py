from enum import Enum
from typing import Optional

import requests
from PyQt5.QtCore import pyqtSignal

from .ProcessWidget import ProcessThread
from ..sessions.qms_session import QMSSession
from ..utils import Account, logger, request_mfa
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError
from auth import ServerError
from jwxt import QuestionnaireTemplate
from qms import QMSAutoJudge, QMSError, QMSQuestionnaire


class JudgeChoice(Enum):
    GET_COURSES = 0
    JUDGE = 1
    EDIT = 2
    JUDGE_ALL = 3


class JudgeThread(ProcessThread):
    questionnaires = pyqtSignal(list, list)
    submitSuccess = pyqtSignal()
    editSuccess = pyqtSignal()

    def __init__(self, account: Account, choice: JudgeChoice, parent=None):
        super().__init__(parent)
        self.account = account
        self.choice = choice
        self.judge_: Optional[QMSAutoJudge] = None
        self.questionnaire: Optional[QMSQuestionnaire] = None
        self.score: int = 100
        self.msgAll: str = ""
        self.scoreAll = None

    @property
    def session(self) -> QMSSession:
        return self.account.session_manager.get_session("qms")

    def login(self) -> bool:
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录学生评教系统..."))
        self.session.ensure_login(
            self.account.username,
            self.account.password,
            account=self.account,
            mfa_provider=self.account.session_manager.mfa_provider,
        )
        self.messageChanged.emit(self.tr("正在进入学生评教系统..."))
        self.judge_ = QMSAutoJudge(self.session)
        self.setIndeterminate.emit(False)
        return True

    @staticmethod
    def _score_percent(score) -> int:
        if score is None:
            return 100
        if isinstance(score, QuestionnaireTemplate.Score):
            return QuestionnaireTemplate.score_to_int(score)
        if isinstance(score, int) and 0 <= score <= 3:
            return {3: 100, 2: 80, 1: 60, 0: 40}[score]
        try:
            return max(0, min(100, int(score)))
        except (TypeError, ValueError):
            return 100

    def _submit_questionnaire(self, questionnaire: QMSQuestionnaire, submit: bool = True) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在提交评教...") if submit else self.tr("正在保存评教..."))
        self.progressChanged.emit(30)
        result, msg = self.judge_.save_answers(
            questionnaire,
            self._score_percent(self.score),
            self.msgAll,
            submit=submit,
        )
        self.progressChanged.emit(100)
        if not result:
            self.error.emit(self.tr("提交失败") if submit else self.tr("保存失败"), msg)
            return False
        return True

    def judge(self) -> bool:
        return self._submit_questionnaire(self.questionnaire, True)

    def edit(self) -> bool:
        if self.questionnaire is None:
            self.error.emit(self.tr("无法编辑"), self.tr("未找到待编辑的问卷"))
            return False
        if self.questionnaire.finished:
            self.messageChanged.emit(self.tr("正在撤回已提交的评教..."))
            ok, msg = self.judge_.recall(self.questionnaire)
            if not ok:
                self.error.emit(self.tr("撤回失败"), msg)
                return False
            unfinished, _ = self.judge_.get_questionnaires()
            for item in unfinished:
                if item.course_id == self.questionnaire.course_id and item.BPJS == self.questionnaire.BPJS:
                    self.questionnaire = item
                    break
        return self._submit_questionnaire(self.questionnaire, True)

    def judge_all(self) -> bool:
        self.setIndeterminate.emit(False)
        self.messageChanged.emit(self.tr("正在获取所有待评教课程..."))
        self.progressChanged.emit(10)
        questionnaires, _ = self.judge_.get_questionnaires()
        if not questionnaires:
            self.error.emit(self.tr("没有待评教课程"), self.tr("所有课程已经完成评教"))
            return False
        total = len(questionnaires)
        success = 0
        failures: list[str] = []
        for index, questionnaire in enumerate(questionnaires):
            if not self.can_run:
                return False
            self.messageChanged.emit(self.tr(f"正在评教第{index + 1}/{total}门：{questionnaire.course_name}"))
            self.progressChanged.emit(10 + int(80 * index / total))
            try:
                result, msg = self.judge_.save_answers(
                    questionnaire,
                    self._score_percent(self.scoreAll),
                    self.msgAll,
                    submit=True,
                )
            except Exception as exc:
                result, msg = False, str(exc)
            if result:
                success += 1
            else:
                failures.append(f"{questionnaire.course_name}（{questionnaire.BPJS}）：{msg}")
                logger.warning("QMS 评教失败：%s %s", questionnaire.course_name, msg)
        self.progressChanged.emit(100)
        if failures:
            details = "\n".join(failures[:10])
            if len(failures) > 10:
                details += f"\n……另有 {len(failures) - 10} 门失败"
            self.error.emit(
                self.tr("部分课程评教失败"),
                self.tr(f"成功 {success}/{total} 门\n{details}"),
            )
            return False
        self.messageChanged.emit(self.tr(f"全部评教完成，共 {success} 门课程"))
        return True

    def run(self):
        self.can_run = True
        if self.account is None:
            self.error.emit(self.tr("未登录"), self.tr("请您先添加一个账户"))
            self.canceled.emit()
            return
        self.progressChanged.emit(0)
        try:
            self.login()
            if self.choice == JudgeChoice.GET_COURSES:
                self.messageChanged.emit(self.tr("正在获取评教任务..."))
                self.progressChanged.emit(50)
                unfinished, finished = self.judge_.get_questionnaires()
                self.progressChanged.emit(100)
                self.questionnaires.emit(unfinished, finished)
                self.hasFinished.emit()
            elif self.choice == JudgeChoice.JUDGE:
                if not self.judge():
                    self.canceled.emit()
                    return
                self.submitSuccess.emit()
                self.hasFinished.emit()
            elif self.choice == JudgeChoice.EDIT:
                if not self.edit():
                    self.canceled.emit()
                    return
                self.editSuccess.emit()
                self.hasFinished.emit()
            elif self.choice == JudgeChoice.JUDGE_ALL:
                if not self.judge_all():
                    self.canceled.emit()
                    return
                self.submitSuccess.emit()
                self.hasFinished.emit()
            else:
                raise ValueError(self.tr("未知选项"))
        except QRCodeLoginCancelledError as e:
            logger.info("二维码登录已取消：%s", e)
            self.error.emit(self.tr("扫码登录已取消"), self.tr("已取消扫码登录，本次操作未完成。"))
            self.canceled.emit()
        except QRCodeLoginUnavailableError as e:
            logger.error("二维码登录交互不可用", exc_info=True)
            self.error.emit(self.tr("登录问题"), str(e))
            self.canceled.emit()
        except MFACancelledError as e:
            logger.info("安全验证已取消：%s", e)
            self.error.emit(self.tr("安全验证已取消"), self.tr("已取消安全验证，本次操作未完成。"))
            self.canceled.emit()
        except MFAUnavailableError as e:
            logger.error("MFA 交互不可用", exc_info=True)
            self.error.emit(self.tr("登录问题"), str(e))
            self.canceled.emit()
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            if e.code == 102:
                self.error.emit(self.tr("登录问题"), self.tr("需要进行两步验证，请前往账户界面，选择对应账户进行验证。"))
                request_mfa(self.account)
            else:
                self.error.emit(self.tr("服务器错误"), e.message)
            self.canceled.emit()
        except QMSError as e:
            logger.error("QMS 接口错误", exc_info=True)
            self.error.emit(self.tr("评教系统错误"), str(e))
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
