from enum import Enum

import requests
from PyQt5.QtCore import pyqtSignal

from auth import ServerError
from lms import LMSUtil
from .ProcessWidget import ProcessThread
from ..utils import accounts, logger


class LMSAction(Enum):
    LOAD_COURSES = "load_courses"
    LOAD_ACTIVITIES = "load_activities"
    LOAD_ACTIVITY_DETAIL = "load_activity_detail"


class LMSThread(ProcessThread):
    coursesLoaded = pyqtSignal(dict, list)
    activitiesLoaded = pyqtSignal(int, list)
    activityDetailLoaded = pyqtSignal(int, dict)

    def __init__(self, parent=None):
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
        self.session.login(accounts.current.username, accounts.current.password)
        self.session.has_login = True
        if not self.can_run:
            return False

        self.util = LMSUtil(self.session)
        self.setIndeterminate.emit(False)
        return True

    def _ensure_util(self) -> bool:
        if self.session.has_login:
            self.util = LMSUtil(self.session)
            return True
        return self.login()

    def run(self):
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
