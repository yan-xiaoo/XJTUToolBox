import concurrent.futures

import requests
from PyQt5.QtCore import pyqtSignal

from auth import ServerError
from .ProcessWidget import ProcessThread
from ..sessions.attendance_session import AttendanceSession
from ..sessions.jwxt_session import JWXTSession
from ..sessions.js_session import JsSession
from ..utils import logger, accounts
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError
from attendance import Attendance
from jwxt.schedule import Schedule


class ScheduleThread(ProcessThread):
    """
    获取课表相关信息的线程。
    课表来源优先级：考勤系统 (bkkq) > 教学服务平台 (js.xjtu.edu.cn)
    考试来源：教务系统 (jwxt)
    """
    schedule = pyqtSignal(dict)
    exam = pyqtSignal(dict)

    def __init__(self, term_number=None, parent=None):
        super().__init__(parent)
        self.term_number = term_number
        self._attendance = None

    @property
    def attendance_session(self) -> AttendanceSession:
        return accounts.current.session_manager.get_session("attendance")

    @property
    def jwxt_session(self) -> JWXTSession:
        return accounts.current.session_manager.get_session("jwxt")

    @property
    def js_session(self) -> JsSession:
        return accounts.current.session_manager.get_session("js")

    def login_attendance(self) -> bool:
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录考勤系统..."))
        self.attendance_session.ensure_login(
            accounts.current.username, accounts.current.password,
            is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE,
            account=accounts.current,
            mfa_provider=accounts.current.session_manager.mfa_provider,
        )
        if not self.can_run:
            return False
        self._attendance = Attendance(
            self.attendance_session,
            is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE,
        )
        self.setIndeterminate.emit(False)
        return True

    def login_jwxt(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录教务系统..."))
        self.jwxt_session.ensure_login(
            accounts.current.username, accounts.current.password,
            account=accounts.current,
            mfa_provider=accounts.current.session_manager.mfa_provider,
        )
        if not self.can_run:
            return False
        self._jwxt_schedule = Schedule(self.jwxt_session)
        self.setIndeterminate.emit(False)
        return True

    def try_bkkq(self, term_name: str) -> list | None:
        """尝试从 bkkq 获取课表，30 秒超时后返回 None。"""
        try:
            self.messageChanged.emit("正在通过考勤系统获取课表...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._attendance.getScheduleLessons, term_name=term_name)
                return future.result(timeout=30)
        except concurrent.futures.TimeoutError:
            logger.warning("bkkq 课表超时 (30s)，切换至回退方案")
            return None
        except Exception as e:
            logger.warning("bkkq 课表获取失败: %s", e)
            return None

    def try_js(self, term_name: str) -> list | None:
        """从 js.xjtu.edu.cn 获取课表（回退方案）。"""
        try:
            self.messageChanged.emit("正在通过教学服务平台获取课表...")
            self.js_session.ensure_login(
                accounts.current.username,
                accounts.current.password,
                account=accounts.current,
                mfa_provider=accounts.current.session_manager.mfa_provider,
            )
            return self.js_session.get_schedule_lessons(term_name)
        except (MFACancelledError, QRCodeLoginCancelledError,
                MFAUnavailableError, QRCodeLoginUnavailableError):
            raise
        except Exception as e:
            logger.warning("js 课表获取失败: %s", e)
            return None

    def run(self):
        self.can_run = True
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        try:
            # ---- 课表来源：bkkq → js 回退 ----
            term_name = self.term_number
            self.progressChanged.emit(25)

            # Step 1: 尝试 bkkq
            bkkq_ok = self.login_attendance()
            lessons = None
            term_info = None
            if bkkq_ok:
                lessons = self.try_bkkq(term_name)
                if lessons is not None:
                    term_info = self._attendance.getNearTerm()

            # Step 2: bkkq 失败 → js 回退
            if lessons is None:
                lessons = self.try_js(term_name)

            if lessons is None:
                raise ServerError(500, self.tr("无法获取课表：所有数据源均失败"))

            start_date = term_info["startdate"] if term_info else None
            term_number = term_name or (term_info["name"] if term_info else "")

            self.progressChanged.emit(66)

            # ---- 考试信息：走 jwxt ----
            self.messageChanged.emit("正在获取考试时间...")
            exam = {}
            exam_term = ""
            try:
                if self.login_jwxt():
                    exam = self._jwxt_schedule.getExamSchedule(timestamp=self.term_number)
                    exam_term = self.term_number or self._jwxt_schedule.termString
            except Exception as e:
                logger.warning("获取考试信息失败，跳过考试查询：%s", e)

            self.progressChanged.emit(100)

        except QRCodeLoginCancelledError as e:
            logger.info("二维码登录已取消：%s", e)
            self.error.emit(self.tr("扫码登录已取消"), self.tr("已取消扫码登录，本次操作未完成。"))
            self.canceled.emit()
        except QRCodeLoginUnavailableError as e:
            logger.error("二维码登录交互不可用", exc_info=True)
            self.error.emit(self.tr("登录问题"), str(e))
            self.canceled.emit()
        except MFACancelledError as e:
            logger.info("MFA 验证已取消：%s", e)
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
        else:
            self.schedule.emit({
                "lessons": lessons,
                "term_number": term_number,
                "start_date": start_date,
            })
            self.exam.emit({
                "exams": exam,
                "term_number": exam_term,
            })
            self.hasFinished.emit()
