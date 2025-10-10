import json
from enum import Enum

import requests

from auth import ServerError
from ..sessions.attendance_session import AttendanceSession
from ..utils import Account, cfg, logger, accounts
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

    def webvpn_login(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在通过 WebVPN 登录考勤系统..."))
        self.session.webvpn_login(self.account.username, self.account.password, is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE)
        self.messageChanged.emit(self.tr("登录 WebVPN 成功。"))

    def normal_login(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在直接登录考勤系统..."))
        self.session.login(self.account.username, self.account.password, is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE)
        self.messageChanged.emit(self.tr("直接登录考勤系统成功。"))

    def search(self, session):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在查询考勤流水..."))
        lookup_wrapper = Attendance(session, use_webvpn=self.last_login_choice == AttendanceFlowChoice.WEBVPN_LOGIN, is_postgraduate=accounts.current.type == accounts.current.POSTGRADUATE)
        while True:
            try:
                result = lookup_wrapper.getFlowRecordWithPage(self.page, self.size)
            except (ServerError, json.JSONDecodeError, requests.Timeout):
                if cfg.autoRetryAttendance.value:
                    self.messageChanged.emit(self.tr("查询考勤流水失败，正在重试..."))
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
            self.webvpn_login()
        else:
            self.normal_login()

    def run(self):
        # 重设自身为可执行
        self.can_run = True
        # 如果用户已经选择过登录方式，就不再更改
        if self.last_login_choice is None:
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
                self.webvpn_login()
                self.last_login_choice = AttendanceFlowChoice.WEBVPN_LOGIN
                self.successMessage.emit(self.tr("WebVPN 登录成功"))
                self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.NORMAL_LOGIN:
                self.normal_login()
                self.last_login_choice = AttendanceFlowChoice.NORMAL_LOGIN
                self.successMessage.emit(self.tr("直接登录考勤系统成功。"))
                self.hasFinished.emit()
            elif self.choice == AttendanceFlowChoice.SEARCH:
                if not self.session.has_login:
                    if self.last_login_choice is not None:
                        self.login_again()
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
