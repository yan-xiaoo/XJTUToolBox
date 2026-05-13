from enum import Enum

import requests
from PyQt5.QtCore import pyqtSignal

from auth import ServerError
from lms import LMSUtil
from .ProcessWidget import ProcessThread
from ..utils import accounts, logger
from ..utils.mfa import MFACancelledError, MFAUnavailableError
from ..utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError


class LMSAction(Enum):
    LOAD_COURSES = "load_courses"
    LOAD_ACTIVITIES = "load_activities"
    LOAD_ACTIVITY_DETAIL = "load_activity_detail"


class LMSThread(ProcessThread):
    coursesLoaded = pyqtSignal(dict, list)
    activitiesLoaded = pyqtSignal(int, list)
    activityDetailLoaded = pyqtSignal(int, dict)

    def __init__(self, parent=None):
        """初始化 LMS 后台线程。

        :param parent: 父级对象，用于 Qt 生命周期管理。
        :return: 无返回值。
        """
        super().__init__(parent)
        self.util: LMSUtil | None = None
        self.action = LMSAction.LOAD_COURSES
        self.course_id: int | None = None
        self.activity_id: int | None = None

    @property
    def session(self):
        return accounts.current.session_manager.get_session("lms")

    def login(self):
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录思源学堂..."))
        self.session.ensure_login(
            accounts.current.username,
            accounts.current.password,
            account=accounts.current,
            mfa_provider=accounts.current.session_manager.mfa_provider,
        )
        if not self.can_run:
            return False

        self.util = LMSUtil(self.session)
        self.setIndeterminate.emit(False)
        return True

    def _ensure_util(self) -> bool:
        return self.login()

    def run(self):
        """根据当前动作执行 LMS 相关后台任务。

        该方法会统一处理课程加载、活动加载和活动详情加载。

        :return: 无返回值。结果通过 Qt 信号异步发回 UI 层。
        """
        self.can_run = True
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        self.progressChanged.emit(0)
        self.setIndeterminate.emit(False)

        try:
            if not self._ensure_util():
                self.canceled.emit()
                return
            if self.util is None:
                raise RuntimeError("LMS util is not initialized")

            if self.action == LMSAction.LOAD_COURSES:
                self.messageChanged.emit(self.tr("正在加载课程列表..."))
                self.progressChanged.emit(40)
                user_info = self.util.get_user_info()
                if not self.can_run:
                    self.canceled.emit()
                    return

                self.progressChanged.emit(70)
                courses = self.util.get_my_courses()
                self.progressChanged.emit(100)
                self.coursesLoaded.emit(user_info, courses)

            elif self.action == LMSAction.LOAD_ACTIVITIES:
                if self.course_id is None:
                    raise ValueError(self.tr("课程 ID 不能为空"))
                self.messageChanged.emit(self.tr("正在加载课程活动..."))
                self.progressChanged.emit(40)
                activities = self.util.get_course_activities(self.course_id)
                self.progressChanged.emit(100)
                self.activitiesLoaded.emit(self.course_id, activities)

            elif self.action == LMSAction.LOAD_ACTIVITY_DETAIL:
                if self.activity_id is None:
                    raise ValueError(self.tr("活动 ID 不能为空"))
                self.messageChanged.emit(self.tr("正在加载活动详情..."))
                self.progressChanged.emit(40)
                detail = self.util.get_activity_detail(self.activity_id)
                self.progressChanged.emit(100)
                self.activityDetailLoaded.emit(self.activity_id, detail)

            else:
                raise ValueError(self.tr("未知的 LMS 操作"))

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
            self.hasFinished.emit()
