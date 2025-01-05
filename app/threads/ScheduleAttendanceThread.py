from enum import Enum

import requests
from PyQt5.QtCore import pyqtSignal

from attendance import Attendance
from auth import ServerError
from .ProcessWidget import ProcessThread
from ..sessions.attendance_session import AttendanceSession
from ..utils import accounts, logger


class AttendanceFlowLogin(Enum):
    WEBVPN_LOGIN = 0
    NORMAL_LOGIN = 1

class ScheduleAttendanceThread(ProcessThread):
    # 返回的结果：第一个结果为考勤信息，第二个结果为考勤流水
    result = pyqtSignal(list, list)
    # 获取考勤流水完成（与监视线程通信）
    water_page_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.util = None
        self.start_date = None
        self.end_date = None
        self.login_method = None

        # 考勤流水（打卡信息）
        self.water_page = []
        # 考勤信息
        self.records = []

    @property
    def session(self) -> AttendanceSession:
        return accounts.current.session_manager.get_session("attendance")

    def webvpn_login(self):
        """
        通过 WebVPN 登录考勤系统
        """
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在通过 WebVPN 登录考勤系统..."))
        self.session.webvpn_login(accounts.current.username, accounts.current.password)
        self.messageChanged.emit(self.tr("登录 WebVPN 成功。"))

    def normal_login(self):
        """
        直接登录考勤系统
        """
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在直接登录考勤系统..."))
        self.session.login(accounts.current.username, accounts.current.password)
        self.messageChanged.emit(self.tr("直接登录考勤系统成功。"))

    def run(self):
        # 强制重置可运行状态
        self.can_run = True
        # 清除结果
        self.water_page = []
        self.records = []
        # 判断当前是否存在账户
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return
        if self.login_method is None:
            self.error.emit(self.tr("未选择登录方式"), self.tr("请先选择登录方式"))
            self.canceled.emit()
            return
        if self.start_date is None or self.end_date is None:
            self.error.emit(self.tr("未选择日期"), self.tr("请先选择日期"))
            self.canceled.emit()
            return

        try:
            # 如果当前账户已经登录，重建代理对象，防止出现 util 和 session 不对应的情况。
            if self.session.has_login:
                self.util = Attendance(self.session, use_webvpn=self.login_method == AttendanceFlowLogin.WEBVPN_LOGIN)
            else:
                # 手动登录。
                if self.login_method == AttendanceFlowLogin.WEBVPN_LOGIN:
                    self.webvpn_login()
                else:
                    self.normal_login()
                self.util = Attendance(self.session, use_webvpn=self.login_method == AttendanceFlowLogin.WEBVPN_LOGIN)
                if not self.can_run:
                    self.canceled.emit()
                    return

            # 查询考勤流水
            self.setIndeterminate.emit(False)
            self.progressChanged.emit(33)
            self.messageChanged.emit(self.tr("正在查询考勤流水..."))
            water_page = self.util.getFlowRecordByTime(self.start_date, self.end_date)
            self.water_page = water_page
            self.water_page_finished.emit()

            if not self.can_run:
                self.result.emit([], water_page)
                self.hasFinished.emit()
                return

            self.progressChanged.emit(66)
            self.messageChanged.emit(self.tr("正在查询考勤信息..."))
            records = self.util.attendanceDetailByTime(self.start_date, self.end_date, 1, 50)
            self.records = records
            self.progressChanged.emit(100)

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
        else:
            self.result.emit(records, water_page)
            self.hasFinished.emit()
