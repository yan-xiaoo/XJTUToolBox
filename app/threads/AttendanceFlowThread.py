import json
import time
from enum import Enum

import requests

from auth import ServerError
from app.sessions.session_backend import AccessMode
from ..sessions.attendance_session import AttendanceSession
from ..utils import Account, cfg, logger, accounts
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError
from attendance.attendance import Attendance
from .ProcessWidget import ProcessThread
from PyQt5.QtCore import pyqtSignal


class AttendanceFlowChoice(Enum):
    WEBVPN_LOGIN = 0
    NORMAL_LOGIN = 1
    SEARCH = 2


class AttendanceFlowThread(ProcessThread):
    # 发送内容：字典。data：数据列表；total_pages：总页数；current_page：当前页数
    flowRecord = pyqtSignal(dict)
    successMessage = pyqtSignal(str)

    def __init__(self, account: Account, choice: AttendanceFlowChoice, size=10, page=1, parent=None):
        super().__init__(parent)
        self.account = account
        self.size = size
        self.page = page
        self.choice = choice
        self.last_login_choice = None

    @property
    def session(self) -> AttendanceSession:
        """
        获取当前账户用于访问考勤系统的 session
        """
        return self.account.session_manager.get_session("attendance")

    def login(self, preferred_access_mode: AccessMode | None = None) -> None:
        """按照统一访问策略登录考勤系统，可传入本次访问方式覆盖。"""
        self.setIndeterminate.emit(True)
        if preferred_access_mode == AccessMode.WEBVPN:
            self.messageChanged.emit(self.tr("正在通过 WebVPN 登录考勤系统..."))
        elif preferred_access_mode == AccessMode.NORMAL:
            self.messageChanged.emit(self.tr("正在直接登录考勤系统..."))
        else:
            self.messageChanged.emit(self.tr("正在登录考勤系统..."))
        self.session.ensure_login(
            self.account.username,
            self.account.password,
            is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE,
            account=self.account,
            mfa_provider=self.account.session_manager.mfa_provider,
            preferred_access_mode=preferred_access_mode,
        )
        self.messageChanged.emit(self.tr("登录考勤系统成功。"))

    def search(self, session):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在查询考勤流水..."))
        lookup_wrapper = Attendance(session, is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE)
        while True:
            try:
                result = lookup_wrapper.getFlowRecordWithPage(self.page, self.size)
            except (ServerError, json.JSONDecodeError, requests.Timeout):
                if cfg.autoRetryAttendance.value:
                    self.messageChanged.emit(self.tr("查询考勤流水失败，正在重试..."))
                    time.sleep(2)
                    continue
                else:
                    raise
            else:
                break
        return result

    def login_again(self):
        """
        根据存储的上次使用的登录方法，再次登录。
        """
        if self.last_login_choice == AttendanceFlowChoice.WEBVPN_LOGIN:
            self.login(AccessMode.WEBVPN)
        else:
            self.login(AccessMode.NORMAL)

    def run(self):
        # 重设自身为可执行
        self.can_run = True
        try:
            if self.account is None:
                raise ValueError(self.tr("账户信息为空"))

            if self.choice == AttendanceFlowChoice.WEBVPN_LOGIN:
                self.login(AccessMode.WEBVPN)
                self.last_login_choice = AttendanceFlowChoice.WEBVPN_LOGIN
                self.successMessage.emit(self.tr("WebVPN 登录成功"))
                self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.NORMAL_LOGIN:
                self.login(AccessMode.NORMAL)
                self.last_login_choice = AttendanceFlowChoice.NORMAL_LOGIN
                self.successMessage.emit(self.tr("直接登录考勤系统成功。"))
                self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.SEARCH:
                if not self.session.has_login or not self.session.validate_login():
                    if self.last_login_choice is not None:
                        self.login_again()
                    else:
                        self.login()
                    result = self.search(self.session)
                    self.flowRecord.emit(result)
                    self.successMessage.emit(self.tr("获得考勤流水成功。"))
                    self.hasFinished.emit()
                else:
                    result = self.search(self.session)
                    self.flowRecord.emit(result)
                    self.successMessage.emit(self.tr("获得考勤流水成功。"))
                    self.hasFinished.emit()
            else:
                raise ValueError(f"{self.choice} is not a valid choice. ")
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
