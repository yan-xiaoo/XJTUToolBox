import time
import traceback
from enum import Enum

import requests

from auth import ServerError
from ..utils import Account, cfg
from auth import get_session
from attendance.attendance import AttendanceWebVPNLogin, AttendanceLogin, Attendance
from .ProcessWidget import ProcessThread
from PyQt5.QtCore import pyqtSignal


class AttendanceFlowChoice(Enum):
    WEBVPN_LOGIN = 0
    NORMAL_LOGIN = 1
    SEARCH = 2


class AttendanceFlowThread(ProcessThread):
    flowRecord = pyqtSignal(list)
    successMessage = pyqtSignal(str)

    def __init__(self, account: Account, choice: AttendanceFlowChoice, size=10, page=1, parent=None):
        super().__init__(parent)
        self.account = account
        self.size = size
        self.page = page
        self.session = None
        self.expire_duration = 600
        self.choice = choice
        self.last_login_choice = None
        # 开始时默认为过期状态，以便在实际使用时刷新
        self.expire_time = time.time() - self.expire_duration

    def has_expired(self):
        return time.time() - self.expire_time > self.expire_duration

    def webvpn_login(self, session):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在通过 WebVPN 登录考勤系统..."))
        attendance_login = AttendanceWebVPNLogin(session)
        attendance_login.login(self.account.username, self.account.password)
        attendance_login.post_login()
        self.messageChanged.emit(self.tr("登录 WebVPN 成功。"))

    def normal_login(self, session):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在直接登录考勤系统..."))
        attendance_login = AttendanceLogin(session)
        attendance_login.login(self.account.username, self.account.password)
        attendance_login.post_login()
        self.messageChanged.emit(self.tr("直接登录考勤系统成功。"))

    def search(self, session):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在查询考勤流水..."))
        lookup_wrapper = Attendance(session, use_webvpn=self.last_login_choice == AttendanceFlowChoice.WEBVPN_LOGIN)
        return lookup_wrapper.getFlowRecord(self.page, self.size)

    def login_again(self, session):
        """
        根据存储的上次使用的登录方法，再次登录。
        :param session: 这应当是一个新的 requests.Session。
        :return: 无
        """
        if self.last_login_choice == AttendanceFlowChoice.WEBVPN_LOGIN:
            self.webvpn_login(session)
        else:
            self.normal_login(session)
        self.reset_expire_time()

    def reset_expire_time(self):
        """重置当前 session 的过期时间为最大值"""
        self.expire_time = time.time()

    def run(self):
        # 根据设置更改登录方式
        setting = cfg.get(cfg.defaultAttendanceLoginMethod)
        if setting == cfg.AttendanceLoginMethod.WEBVPN:
            self.last_login_choice = AttendanceFlowChoice.WEBVPN_LOGIN
        elif setting == cfg.AttendanceLoginMethod.NORMAL:
            self.last_login_choice = AttendanceFlowChoice.NORMAL_LOGIN

        try:
            if self.account is None:
                raise ValueError(self.tr("账户信息为空"))

            if self.choice == AttendanceFlowChoice.WEBVPN_LOGIN:
                if not self.has_expired():
                    self.successMessage.emit(self.tr("无需重新登录。"))
                    self.hasFinished.emit()
                    return
                else:
                    self.session = get_session()
                    self.webvpn_login(self.session)
                    self.reset_expire_time()
                    self.last_login_choice = AttendanceFlowChoice.WEBVPN_LOGIN
                    self.successMessage.emit(self.tr("WebVPN 登录成功"))
                    self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.NORMAL_LOGIN:
                if not self.has_expired():
                    self.successMessage.emit(self.tr("无需重新登录。"))
                    self.hasFinished.emit()
                else:
                    self.session = get_session()
                    self.normal_login(self.session)
                    self.reset_expire_time()
                    self.last_login_choice = AttendanceFlowChoice.NORMAL_LOGIN
                    self.successMessage.emit(self.tr("直接登录考勤系统成功。"))
                    self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.SEARCH:
                if self.has_expired():
                    if self.last_login_choice is not None:
                        self.session = get_session()
                        self.login_again(self.session)
                        result = self.search(self.session)
                        self.flowRecord.emit(result)
                        self.successMessage.emit(self.tr("获得考勤流水成功。"))
                        self.hasFinished.emit()
                    else:
                        self.error.emit(self.tr("请先选择一种方式登录"), "")
                        self.canceled.emit()
                else:
                    result = self.search(self.session)
                    self.flowRecord.emit(result)
                    self.successMessage.emit(self.tr("获得考勤流水成功。"))
                    self.hasFinished.emit()
            else:
                raise ValueError(f"{self.choice} is not a valid choice. ")
        except ServerError as e:
            self.error.emit(self.tr("服务器错误"), e.message)
            self.canceled.emit()
        except requests.RequestException as e:
            self.error.emit(self.tr("网络错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            traceback.print_exc()
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()

    def reset(self):
        """设置当前内容为已过期，从而强制下一次调用时刷新 session"""
        self.expire_time = time.time() - self.expire_duration
