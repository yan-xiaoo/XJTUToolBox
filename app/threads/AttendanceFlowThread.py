import json
import time

import requests

from auth import ServerError
from ..sessions.attendance_session import AttendanceSession
from ..utils import Account, cfg, logger, accounts
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError
from attendance.attendance import Attendance
from .ProcessWidget import ProcessThread
from PyQt5.QtCore import QObject, pyqtSignal


class AttendanceFlowThread(ProcessThread):
    # 发送内容：字典。data：数据列表；total_pages：总页数；current_page：当前页数
    flowRecord = pyqtSignal(dict)
    successMessage = pyqtSignal(str)

    def __init__(self, account: Account | None, size: int = 10, page: int = 1,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.account = account
        self.size = size
        self.page = page

    @property
    def session(self) -> AttendanceSession:
        """
        获取当前账户用于访问考勤系统的 session
        """
        if self.account is None:
            raise ValueError(self.tr("账户信息为空"))
        return self.account.session_manager.get_session("attendance")

    def login(self) -> bool:
        """按照统一访问策略确保考勤系统已登录。"""
        if self.account is None:
            raise ValueError(self.tr("账户信息为空"))

        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在检查考勤系统登录状态..."))
        did_login = self.session.ensure_login(
            self.account.username,
            self.account.password,
            is_postgraduate=self.account.type == self.account.POSTGRADUATE,
            account=self.account,
            mfa_provider=self.account.session_manager.mfa_provider,
        )
        if did_login:
            self.messageChanged.emit(self.tr("登录考勤系统成功。"))
        else:
            self.messageChanged.emit(self.tr("考勤系统登录状态有效。"))
        return did_login

    def search(self, session: AttendanceSession) -> dict[str, object]:
        if self.account is None:
            raise ValueError(self.tr("账户信息为空"))

        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在查询考勤流水..."))
        lookup_wrapper = Attendance(session, is_postgraduate=self.account.type == self.account.POSTGRADUATE)
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

    def run(self) -> None:
        # 重设自身为可执行
        self.can_run = True
        try:
            if self.account is None:
                raise ValueError(self.tr("账户信息为空"))

            self.login()
            result = self.search(self.session)
            self.flowRecord.emit(result)
            self.successMessage.emit(self.tr("获得考勤流水成功。"))
            self.hasFinished.emit()
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
