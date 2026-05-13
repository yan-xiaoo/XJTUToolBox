import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Any
from urllib.parse import urlparse, unquote

from PyQt5.QtCore import pyqtSlot, Qt, QUrl, QStandardPaths, QBuffer
from PyQt5.QtGui import QDesktopServices, QImageReader, QPixmap
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QFileDialog, QSizePolicy
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, InfoBar, InfoBarPosition, BreadcrumbBar, \
    TransparentToolButton, FluentIcon

from .components.ProgressInfoBar import ProgressInfoBar
from .sessions.lms_session import LMSSession
from .sessions.session_backend import AccessMode
from .threads.LMSFileDownloadThread import LMSFileDownloadThread
from .threads.LMSThread import LMSThread, LMSAction
from .threads.ProcessWidget import ProcessWidget
from .utils import StyleSheet, accounts, AccountDataManager, cfg
from .sub_interfaces.lms import PageStatus, LMSStartPage, LMSCoursePage, LMSActivityPage, LMSDetailPage, LMSSubmissionPage, LMSVideoPage
from .sub_interfaces.lms.image_preview_dialog import LMSImagePreviewDialog
from .sub_interfaces.lms.common import format_size as common_format_size, format_replay_video_label, \
    can_preview_as_image, is_mark_attachment_upload
from auth import getVPNUrl
from lms import LMSUtil
from lms.models import ActivityType


class LMSInterface(ScrollArea):
    # 所有子页面的 ROUTE_KEY，用于在导航中标记页面。
    ROUTE_START = "startPage"
    ROUTE_COURSE = "coursePage"
    ROUTE_ACTIVITY = "activityPage"
    ROUTE_DETAIL = "detailPage"
    ROUTE_SUBMISSION = "submissionPage"
    ROUTE_VIDEO = "videoPage"
    COURSE_CACHE_FILE = "lms_courses_cache.json"
    ACTIVITY_CACHE_FILE = "lms_activities_cache.json"

    def __init__(self, parent=None):
        """初始化 LMS 主容器、导航区、页面区与线程协作组件。"""
        super().__init__(parent)

        self._onlyNotice = None
        self.selected_course_id: Optional[int] = None
        self.selected_activity_id: Optional[int] = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_submission: Optional[dict] = None
        self._download_jobs: list[tuple[ProgressInfoBar, LMSFileDownloadThread]] = []
        self._current_activities: list[dict] = []
        self._preview_pixmap_cache: dict[str, QPixmap] = {}
        self._mark_overlay_cache: dict[str, tuple[str | None, list[dict]]] = {}
        self._submission_marked_attachment_cache: dict[int, dict] = {}
        self._preview_dialog: LMSImagePreviewDialog | None = None
        self._course_cache_visible_during_refresh = False
        self._activity_cache_visible_during_refresh = False

        self.view = QWidget(self)
        self.setObjectName("LMSInterface")
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        self.titleLabel = TitleLabel(self.tr("思源学堂"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.minorLabel = StrongBodyLabel(self.tr("选择课程、查看活动并浏览详细内容"), self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.minorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.vBoxLayout.addWidget(self.minorLabel)
        self.titleSpacer = QWidget(self.view)
        self.titleSpacer.setFixedHeight(10)
        self.vBoxLayout.addWidget(self.titleSpacer)

        self.contentFrame = QFrame(self.view)
        self.contentLayout = QVBoxLayout(self.contentFrame)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.setSpacing(10)

        self.navFrame = QFrame(self.contentFrame)
        self.navLayout = QHBoxLayout(self.navFrame)
        self.navLayout.setContentsMargins(0, 0, 0, 0)
        self.navLayout.setSpacing(8)

        self.returnButton = TransparentToolButton(FluentIcon.RETURN, self.navFrame)
        self.returnButton.setToolTip(self.tr("返回"))
        self.returnButton.clicked.connect(self.onReturnButtonClicked)

        self.breadcrumbBar = BreadcrumbBar(self.navFrame)
        self.breadcrumbBar.setSpacing(20)
        self.breadcrumbBar.currentItemChanged.connect(self.onBreadcrumbChanged)

        self.navLayout.addWidget(self.returnButton, alignment=Qt.AlignVCenter)
        self.navLayout.addWidget(self.breadcrumbBar, stretch=1, alignment=Qt.AlignVCenter)

        self.thread_ = LMSThread()
        self.processWidget = ProcessWidget(self.thread_, self.view, stoppable=True, hide_on_end=True)
        self.processWidget.setVisible(False)
        self.contentLayout.addWidget(self.processWidget)
        self.contentLayout.addWidget(self.navFrame)

        self.pageHost = QWidget(self.view)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.pageLayout.setSpacing(0)
        self.contentLayout.addWidget(self.pageHost)
        self.vBoxLayout.addWidget(self.contentFrame)

        self._initPages()
        self._initNavigationModel()
        self._connectSignals()

        self._current_page = self.startPage
        self.switchPage(self.startPage)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        StyleSheet.LMS_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

    def _initPages(self):
        """创建并挂载六个子页面。"""
        self.startPage = LMSStartPage(self)
        self.coursePage = LMSCoursePage(self)
        self.activityPage = LMSActivityPage(self)
        self.detailPage = LMSDetailPage(self)
        self.submissionPage = LMSSubmissionPage(self)
        self.videoPage = LMSVideoPage(self)

        self.pageLayout.addWidget(self.startPage)
        self.pageLayout.addWidget(self.coursePage)
        self.pageLayout.addWidget(self.activityPage)
        self.pageLayout.addWidget(self.detailPage)
        self.pageLayout.addWidget(self.submissionPage)
        self.pageLayout.addWidget(self.videoPage)

    def _connectSignals(self):
        """连接线程信号与子页面信号。"""
        self.thread_.error.connect(self.onThreadError)
        self.thread_.coursesLoaded.connect(self.onCoursesLoaded)
        self.thread_.activitiesLoaded.connect(self.onActivitiesLoaded)
        self.thread_.activityDetailLoaded.connect(self.onActivityDetailLoaded)
        self.thread_.finished.connect(self.unlock)

        self.startPage.queryCoursesRequested.connect(self.onStartQueryCoursesClicked)
        self.coursePage.retryRequested.connect(self.refreshCourses)
        self.coursePage.courseSelected.connect(self.onCourseSelected)
        self.activityPage.retryRequested.connect(self.refreshActivities)
        self.activityPage.activitySelected.connect(self.onActivitySelected)
        self.detailPage.retryRequested.connect(self.refreshActivityDetail)
        self.detailPage.submissionRequested.connect(self.show_submission_page)
        self.detailPage.downloadRequested.connect(self._save_file)
        self.detailPage.previewRequested.connect(self.show_attachment_preview)
        self.detailPage.replayVideoViewRequested.connect(self.show_video_page)
        self.detailPage.relatedLessonRequested.connect(self.openRelatedLesson)
        self.submissionPage.downloadRequested.connect(self._save_file)
        self.submissionPage.previewRequested.connect(self.show_attachment_preview)
        self.submissionPage.reviewPreviewRequested.connect(self.show_attachment_review_preview)
        self.submissionPage.markedAttachmentsDebugRequested.connect(self.dump_current_submission_marked_attachments)

    def _initNavigationModel(self):
        """初始化页面与路由键的双向映射。"""
        self._page_route_map = {
            self.startPage: self.ROUTE_START,
            self.coursePage: self.ROUTE_COURSE,
            self.activityPage: self.ROUTE_ACTIVITY,
            self.detailPage: self.ROUTE_DETAIL,
            self.submissionPage: self.ROUTE_SUBMISSION,
            self.videoPage: self.ROUTE_VIDEO,
        }
        self._route_page_map = {route: page for page, route in self._page_route_map.items()}

    def switchPage(self, page: QWidget):
        """切换当前显示页面并滚动回顶部。

        :param page: 目标页面对象（start/course/activity/detail/submission/video 之一）。
        :return: 无返回值。
        """
        # 如果从视频播放页面切换出去，那么需要停止视频的播放。
        if getattr(self, "_current_page", None) is self.videoPage and page is not self.videoPage:
            self.videoPage.stopPlayback()

        self._current_page = page
        pages = (self.startPage, self.coursePage, self.activityPage, self.detailPage, self.submissionPage, self.videoPage)
        for one in pages:
            one.setVisible(one is page)

        self._updatePageHeader(page)

        self.pageHost.adjustSize()
        self.view.adjustSize()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().setValue(0)

    def _updatePageHeader(self, page: QWidget):
        """根据页面类型更新标题区与导航区显隐。"""
        on_start_page = page is self.startPage
        self.titleLabel.setVisible(on_start_page)
        self.minorLabel.setVisible(on_start_page)
        self.titleSpacer.setVisible(on_start_page)
        self.navFrame.setVisible(not on_start_page)

    def _initBreadcrumbRoot(self, switch_page: bool = True):
        """重置面包屑到根节点（课程列表）。"""
        self.breadcrumbBar.blockSignals(True)
        self.breadcrumbBar.clear()
        self.breadcrumbBar.addItem(self.ROUTE_COURSE, self.tr("课程列表"))
        self.breadcrumbBar.blockSignals(False)
        if switch_page:
            self.switchPage(self.coursePage)
        self._updateReturnButtonState()

    @pyqtSlot()
    def onStartQueryCoursesClicked(self):
        """处理起始页“查询我的课程”事件并启动课程加载。

        :return: 无返回值。
        """
        self._initBreadcrumbRoot(switch_page=True)
        self.refreshCourses()

    @staticmethod
    def _truncateBreadcrumbLabel(text: str, limit: int = 20) -> str:
        """截断过长的面包屑标题文本。"""
        safe = str(text or "-")
        if len(safe) > limit:
            return f"{safe[:limit]}..."
        return safe

    def navigate_to(self, page: QFrame, label: str):
        """向面包屑追加层级并导航到指定页面。

        :param page: 目标页面对象。
        :param label: 显示在面包屑中的文本。
        :return: 无返回值。
        """
        route_key = self._page_route_map.get(page)
        if not route_key:
            return
        display_text = label
        if route_key in {self.ROUTE_ACTIVITY, self.ROUTE_DETAIL}:
            display_text = self._truncateBreadcrumbLabel(label)

        self.breadcrumbBar.blockSignals(True)
        self.breadcrumbBar.addItem(route_key, display_text)
        self.breadcrumbBar.blockSignals(False)

        self.switchPage(page)
        self._updateReturnButtonState()

    @pyqtSlot()
    def onReturnButtonClicked(self):
        """处理返回按钮点击，回退到上一级面包屑页面。

        :return: 无返回值。
        """
        if len(self.breadcrumbBar.items) <= 1:
            self._updateReturnButtonState()
            return
        self.breadcrumbBar.setCurrentIndex(len(self.breadcrumbBar.items) - 2)

    @pyqtSlot(str)
    def onBreadcrumbChanged(self, route_key: str):
        """处理面包屑当前项变化并切换对应页面。

        :param route_key: 当前面包屑项对应的路由键。
        :return: 无返回值。
        """
        target_page = self._route_page_map.get(route_key)
        if target_page is not None:
            self.switchPage(target_page)
        self._updateReturnButtonState()

    def _updateReturnButtonState(self):
        """根据面包屑层级刷新返回按钮可用状态。"""
        self.returnButton.setEnabled(len(self.breadcrumbBar.items) > 1)

    def setPageStatus(self, page: QWidget, status: PageStatus):
        """设置指定子页面的显示状态。

        :param page: 目标页面对象（课程页/活动页/详情页）。
        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if page is self.coursePage:
            self.coursePage.setPageStatus(status)
        elif page is self.activityPage:
            self.activityPage.setPageStatus(status)
        elif page is self.detailPage:
            self.detailPage.setPageStatus(status)

    def _getAccountCacheManager(self) -> AccountDataManager | None:
        current_account = accounts.current
        if current_account is None:
            return None
        return AccountDataManager(current_account)

    @staticmethod
    def _isLmsCacheEnabled() -> bool:
        return bool(cfg.lmsCacheEnable.value)

    def _getLmsCacheFilePath(self, filename: str) -> str | None:
        current_account = accounts.current
        if current_account is None:
            return None

        manager = self._getAccountCacheManager()
        if manager is None:
            return None
        return manager.path(filename)

    @staticmethod
    def _sanitizeCacheItems(items: object) -> list[dict]:
        if not isinstance(items, list):
            return []
        return [dict(one) for one in items if isinstance(one, dict)]

    @staticmethod
    def _stableDump(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))

    def _readCoursesCache(self) -> list[dict]:
        if not self._isLmsCacheEnabled():
            return []
        file_path = self._getLmsCacheFilePath(self.COURSE_CACHE_FILE)
        if not file_path:
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []
        if not isinstance(payload, dict):
            return []
        return self._sanitizeCacheItems(payload.get("courses"))

    def _writeCoursesCache(self, courses: list[dict]) -> None:
        if not self._isLmsCacheEnabled():
            return
        file_path = self._getLmsCacheFilePath(self.COURSE_CACHE_FILE)
        if not file_path:
            return
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"courses": self._sanitizeCacheItems(courses)}, f, ensure_ascii=False)
        except (OSError, TypeError, ValueError):
            return

    def _readActivityCacheMap(self) -> dict[str, list[dict]]:
        if not self._isLmsCacheEnabled():
            return {}
        file_path = self._getLmsCacheFilePath(self.ACTIVITY_CACHE_FILE)
        if not file_path:
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        by_course = payload.get("by_course_id")
        if not isinstance(by_course, dict):
            return {}

        normalized: dict[str, list[dict]] = {}
        for raw_key, raw_value in by_course.items():
            key = str(raw_key).strip()
            if not key:
                continue
            normalized[key] = self._sanitizeCacheItems(raw_value)
        return normalized

    def _readActivitiesCache(self, course_id: int) -> list[dict]:
        return self._readActivityCacheMap().get(str(course_id), [])

    def _writeActivitiesCache(self, course_id: int, activities: list[dict]) -> None:
        if not self._isLmsCacheEnabled():
            return
        file_path = self._getLmsCacheFilePath(self.ACTIVITY_CACHE_FILE)
        if not file_path:
            return
        by_course = self._readActivityCacheMap()
        by_course[str(course_id)] = self._sanitizeCacheItems(activities)
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"by_course_id": by_course}, f, ensure_ascii=False)
        except (OSError, TypeError, ValueError):
            return

    def _diffById(self, old_items: list[dict], new_items: list[dict]) -> dict[str, Any]:
        old_rows = self._sanitizeCacheItems(old_items)
        new_rows = self._sanitizeCacheItems(new_items)

        old_non_int_id = any(not isinstance(one.get("id"), int) for one in old_rows)
        new_non_int_id = any(not isinstance(one.get("id"), int) for one in new_rows)
        if old_non_int_id or new_non_int_id:
            identical = self._stableDump(old_rows) == self._stableDump(new_rows)
            return {
                "identical": identical,
                "full_replace": not identical,
                "upserts": [],
                "new_count": 0,
                "updated_count": 0,
            }

        old_by_id = {int(one["id"]): one for one in old_rows}
        new_by_id = {int(one["id"]): one for one in new_rows}
        has_removal = any(one_id not in new_by_id for one_id in old_by_id)

        upserts: list[dict] = []
        new_count = 0
        updated_count = 0
        for row in new_rows:
            row_id = int(row["id"])
            old_row = old_by_id.get(row_id)
            if old_row is None:
                upserts.append(row)
                new_count += 1
                continue
            if self._stableDump(old_row) != self._stableDump(row):
                upserts.append(row)
                updated_count += 1

        identical = not has_removal and not upserts and len(old_by_id) == len(new_by_id)
        return {
            "identical": identical,
            "full_replace": has_removal,
            "upserts": upserts,
            "new_count": new_count,
            "updated_count": updated_count,
        }

    def _showCachedCoursesIfAvailable(self) -> bool:
        cached_courses = self._readCoursesCache()
        if not cached_courses:
            return False
        self.coursePage.setCourses(cached_courses)
        self.setPageStatus(self.coursePage, PageStatus.NORMAL)
        return True

    def _showCachedActivitiesIfAvailable(self, course_id: int) -> bool:
        cached_activities = self._readActivitiesCache(course_id)
        if not cached_activities:
            return False
        self.activityPage.setActivities(cached_activities)
        self.setPageStatus(self.activityPage, PageStatus.NORMAL)
        return True

    def lock(self):
        """锁定主界面交互，防止加载过程中的重复操作。

        :return: 无返回值。
        """
        self.returnButton.setEnabled(False)
        self.startPage.setInteractionEnabled(False)
        self.coursePage.setInteractionEnabled(False)
        self.activityPage.setInteractionEnabled(False)

    def unlock(self):
        """恢复主界面交互状态。

        :return: 无返回值。
        """
        self._updateReturnButtonState()
        self.startPage.setInteractionEnabled(True)
        self.coursePage.setInteractionEnabled(True)
        self.activityPage.setInteractionEnabled(True)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """显示成功通知。

        :param title: 通知标题。
        :param msg: 通知正文。
        :param duration: 自动关闭时长（毫秒）。
        :param position: 通知显示位置。
        :param parent: 通知父组件。
        :return: 无返回值。
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.success(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def error(self, title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """显示错误通知。

        :param title: 通知标题。
        :param msg: 通知正文。
        :param duration: 自动关闭时长（毫秒）。
        :param position: 通知显示位置。
        :param parent: 通知父组件。
        :return: 无返回值。
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        """统一处理线程错误并切换当前页为错误态。

        :param title: 错误标题。
        :param msg: 错误详情。
        :return: 无返回值。
        """
        self.error(title, msg, parent=self)

        action = self.thread_.action
        if action == LMSAction.LOAD_COURSES:
            keep_cached = self._course_cache_visible_during_refresh and bool(self.coursePage.getCoursesSnapshot())
            self._course_cache_visible_during_refresh = False
            if keep_cached:
                self.setPageStatus(self.coursePage, PageStatus.NORMAL)
                return
        elif action == LMSAction.LOAD_ACTIVITIES:
            keep_cached = self._activity_cache_visible_during_refresh and bool(self.activityPage.getActivitiesSnapshot())
            self._activity_cache_visible_during_refresh = False
            if keep_cached:
                self.setPageStatus(self.activityPage, PageStatus.NORMAL)
                return

        self.setPageStatus(self._current_page, PageStatus.ERROR)

    @pyqtSlot()
    def refreshCourses(self):
        """触发课程列表异步加载。

        :return: 无返回值。
        """
        has_visible_data = bool(self.coursePage.getCoursesSnapshot())
        if not has_visible_data:
            has_visible_data = self._showCachedCoursesIfAvailable()
        self._course_cache_visible_during_refresh = has_visible_data
        self.setPageStatus(self.coursePage, PageStatus.NORMAL if has_visible_data else PageStatus.LOADING)
        self.switchPage(self.coursePage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread_.action = LMSAction.LOAD_COURSES
        self.thread_.start()

    @pyqtSlot()
    def refreshActivities(self):
        """触发当前课程的活动列表异步加载。

        :return: 无返回值。
        """
        if self.selected_course_id is None:
            self.error(self.tr("未选择课程"), self.tr("请先选择一门课程"), parent=self)
            return
        has_visible_data = bool(self.activityPage.getActivitiesSnapshot())
        if not has_visible_data:
            has_visible_data = self._showCachedActivitiesIfAvailable(self.selected_course_id)
        self._activity_cache_visible_during_refresh = has_visible_data
        self.setPageStatus(self.activityPage, PageStatus.NORMAL if has_visible_data else PageStatus.LOADING)
        self.switchPage(self.activityPage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread_.action = LMSAction.LOAD_ACTIVITIES
        self.thread_.course_id = self.selected_course_id
        self.thread_.start()

    def refreshActivityDetail(self):
        """触发当前活动详情异步加载。

        :return: 无返回值。
        """
        if self.selected_activity_id is None:
            self.error(self.tr("未选择活动"), self.tr("请先选择一个活动"), parent=self)
            return
        self.setPageStatus(self.detailPage, PageStatus.LOADING)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread_.action = LMSAction.LOAD_ACTIVITY_DETAIL
        self.thread_.activity_id = self.selected_activity_id
        self.thread_.start()

    @pyqtSlot(str)
    def openRelatedLesson(self, lesson_start_time: str):
        """根据直播详情中的开始时间直接跳转到对应回放活动。

        :param lesson_start_time: 直播详情中提取出的对应回放开始时间。
        :return: 无返回值。
        """
        lesson = self._findRelatedLessonActivity(lesson_start_time)
        lesson_id = lesson.get("id")
        lesson_name = str(lesson.get("title") or "-") if isinstance(lesson, dict) else "-"
        if not isinstance(lesson_id, int):
            self.error(
                self.tr("未找到对应回放"),
                self.tr("当前直播开始时间为 {0}，但课程中没有匹配的回放活动。").format(lesson_start_time),
                parent=self,
            )
            return

        self.selected_activity_id = lesson_id
        self.selected_activity_name = lesson_name
        self.activityPage.setCurrentActivityType(ActivityType.LESSON.value)
        self._updateDetailBreadcrumbLabel(lesson_name)
        self.refreshActivityDetail()

    @pyqtSlot(int, str)
    def onCourseSelected(self, course_id: int, course_name: str):
        """处理课程选择事件并进入活动页。

        :param course_id: 课程 ID。
        :param course_name: 课程名称。
        :return: 无返回值。
        """
        self.selected_course_id = course_id
        self.selected_course_name = course_name
        self.selected_activity_id = None
        self.selected_activity_name = ""
        self._current_activities = []

        self.activityPage.setCurrentActivityType(ActivityType.HOMEWORK.value)
        self.activityPage.clearData()
        self._showCachedActivitiesIfAvailable(course_id)

        self.navigate_to(self.activityPage, self.selected_course_name)
        self.refreshActivities()

    @pyqtSlot(int, str)
    def onActivitySelected(self, activity_id: int, activity_name: str):
        """处理活动选择事件并进入详情页。

        :param activity_id: 活动 ID。
        :param activity_name: 活动标题。
        :return: 无返回值。
        """
        self.selected_activity_id = activity_id
        self.selected_activity_name = activity_name
        self.navigate_to(self.detailPage, self.selected_activity_name)
        self.refreshActivityDetail()

    @pyqtSlot(dict, list)
    def onCoursesLoaded(self, _user_info: dict, courses: list):
        """处理课程加载完成回调并下发到课程页。

        :param _user_info: 用户信息（当前实现中未使用）。
        :param courses: 课程列表。
        :return: 无返回值。
        """
        network_courses = self._sanitizeCacheItems(courses)
        current_courses = self.coursePage.getCoursesSnapshot()
        had_cached_view = self._course_cache_visible_during_refresh
        self._course_cache_visible_during_refresh = False

        self.setPageStatus(self.coursePage, PageStatus.NORMAL)

        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_submission = None
        self._current_activities = []
        self._preview_pixmap_cache.clear()
        self._mark_overlay_cache.clear()
        self._submission_marked_attachment_cache.clear()
        if self._preview_dialog is not None:
            self._preview_dialog.close()

        self.activityPage.reset()
        self.detailPage.reset()
        self.submissionPage.reset()
        self.videoPage.reset()

        if not current_courses:
            diff = {
                "identical": False,
                "full_replace": True,
                "upserts": [],
                "new_count": len(network_courses),
                "updated_count": 0,
            }
        else:
            diff = self._diffById(current_courses, network_courses)

        if not current_courses or diff["full_replace"]:
            self.coursePage.setCourses(network_courses)
        elif not diff["identical"] and diff["upserts"]:
            self.coursePage.upsertCourses(diff["upserts"])

        self._writeCoursesCache(network_courses)

        if network_courses:
            if current_courses and not diff["identical"] and not diff["full_replace"]:
                self.success(
                    self.tr("课程已更新"),
                    self.tr("新增 {0} 门，更新 {1} 门课程").format(diff["new_count"], diff["updated_count"]),
                    parent=self
                )
            elif had_cached_view and diff["identical"]:
                self.success(self.tr("课程已是最新"), self.tr("缓存与网络数据一致"), parent=self)
            else:
                self.success(self.tr("加载完成"), self.tr("已获取 {0} 门课程").format(len(network_courses)), parent=self)
        else:
            self.success(self.tr("暂无课程"), self.tr("当前账号未获取到课程"), parent=self)

    @pyqtSlot(int, list)
    def onActivitiesLoaded(self, course_id: int, activities: list):
        """处理活动加载完成回调并下发到活动页。

        :param course_id: 返回数据所属的课程 ID。
        :param activities: 活动列表。
        :return: 无返回值。
        """
        network_activities = self._sanitizeCacheItems(activities)
        current_activities = self.activityPage.getActivitiesSnapshot()
        had_cached_view = self._activity_cache_visible_during_refresh
        self._activity_cache_visible_during_refresh = False

        self.setPageStatus(self.activityPage, PageStatus.NORMAL)
        if self.selected_course_id != course_id:
            return

        if not current_activities:
            diff = {
                "identical": False,
                "full_replace": True,
                "upserts": [],
                "new_count": len(network_activities),
                "updated_count": 0,
            }
        else:
            diff = self._diffById(current_activities, network_activities)

        if not current_activities or diff["full_replace"]:
            self.activityPage.setActivities(network_activities)
        elif not diff["identical"] and diff["upserts"]:
            self.activityPage.upsertActivities(diff["upserts"])

        self._current_activities = network_activities
        self._writeActivitiesCache(course_id, network_activities)
        self.switchPage(self.activityPage)
        if not network_activities:
            self.success(self.tr("无活动"), self.tr("该课程暂无可显示活动"), parent=self)
            return

        if current_activities and not diff["identical"] and not diff["full_replace"]:
            homework_updates = [
                one for one in diff["upserts"]
                if isinstance(one, dict) and str(one.get("type") or "") == ActivityType.HOMEWORK.value
            ]
            if homework_updates:
                self.success(
                    self.tr("作业已更新"),
                    self.tr("本课程有 {0} 项作业已新增或更新").format(len(homework_updates)),
                    parent=self
                )
        elif had_cached_view and diff["identical"]:
            self.success(self.tr("作业已是最新"), self.tr("缓存与网络数据一致"), parent=self)

    @pyqtSlot(int, dict)
    def onActivityDetailLoaded(self, activity_id: int, detail: dict):
        """处理活动详情加载回调并下发到详情页。

        :param activity_id: 返回数据所属的活动 ID。
        :param detail: 活动详情字典。
        :return: 无返回值。
        """
        self.setPageStatus(self.detailPage, PageStatus.NORMAL)
        if self.selected_activity_id != activity_id:
            return
        self.detailPage.setDetail(detail, self.selected_course_name, self.selected_activity_name)

    @pyqtSlot(dict)
    def show_submission_page(self, submission: dict):
        """展示提交详情页。

        :param submission: 单次提交详情字典。
        :return: 无返回值。
        """
        self._ensure_submission_marked_attachments_loaded(submission, force=True)
        self._current_submission = submission
        self.submissionPage.setSubmission(submission, self.selected_course_name, self.selected_activity_name)
        self.navigate_to(self.submissionPage, self.tr("提交详情"))

    def ensure_lms_login(self) -> tuple[LMSSession | None, str | None]:
        """确保当前账户已经登录思源学堂，并返回可用 session。"""
        current_account = accounts.current
        if current_account is None:
            return None, self.tr("请先添加一个账户")
        try:
            session = current_account.session_manager.get_session("lms")
            session.ensure_login(
                current_account.username,
                current_account.password,
                account=current_account,
                mfa_provider=current_account.session_manager.mfa_provider,
            )
        except Exception as e:
            return None, str(e)
        return session, None

    def _get_lms_util(self) -> LMSUtil | None:
        session, _ = self.ensure_lms_login()
        if session is None:
            return None
        return LMSUtil(session)

    def _ensure_submission_marked_attachments_loaded(self, submission: dict | None, *, force: bool = False) -> bool:
        if not isinstance(submission, dict):
            return False

        submission_id = submission.get("id")
        if not isinstance(submission_id, int):
            return False

        marked_data = None if force else self._submission_marked_attachment_cache.get(submission_id)
        util = None
        if marked_data is None:
            util = self._get_lms_util()
            if util is None:
                return False
            try:
                marked_data = util.get_submission_marked_attachments(submission_id)
            except Exception:
                return False
            if isinstance(marked_data, dict):
                self._submission_marked_attachment_cache[submission_id] = marked_data

        if not isinstance(marked_data, dict):
            return False
        submission["marked_attachments"] = dict(marked_data)
        return True

    @staticmethod
    def _find_matching_upload_row(target: dict | None, rows: list[dict]) -> dict | None:
        if not isinstance(target, dict):
            return None

        strong_keys = ("id", "reference_id", "key", "download_url", "preview_url", "attachment_url")
        for key in strong_keys:
            candidate = target.get(key)
            if candidate in (None, ""):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get(key) == candidate:
                    return row

        candidate_name = target.get("name")
        if candidate_name not in (None, ""):
            matched_by_name = [
                row for row in rows
                if isinstance(row, dict) and row.get("name") == candidate_name
            ]
            if len(matched_by_name) == 1:
                return matched_by_name[0]

        for row in rows:
            if not isinstance(row, dict):
                continue
            if row is target:
                return row
        return None

    @staticmethod
    def _find_upload_index(target: dict | None, rows: list[dict]) -> int | None:
        if not isinstance(target, dict):
            return None

        for index, row in enumerate(rows):
            if row is target:
                return index

        strong_keys = ("id", "reference_id", "key", "download_url", "preview_url", "attachment_url")
        for key in strong_keys:
            candidate = target.get(key)
            if candidate in (None, ""):
                continue
            matches = [
                index for index, row in enumerate(rows)
                if isinstance(row, dict) and row.get(key) == candidate
            ]
            if len(matches) == 1:
                return matches[0]

        candidate_name = target.get("name")
        if candidate_name not in (None, ""):
            matches = [
                index for index, row in enumerate(rows)
                if isinstance(row, dict) and row.get("name") == candidate_name
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    @pyqtSlot()
    def dump_current_submission_marked_attachments(self):
        submission = self._current_submission
        if not isinstance(submission, dict):
            self.error(self.tr("无法输出"), self.tr("当前没有可用的提交详情"), parent=self)
            return

        self._ensure_submission_marked_attachments_loaded(submission, force=True)
        submission_id = submission.get("id")
        marked_data = submission.get("marked_attachments")
        rules = []
        if isinstance(marked_data, dict):
            maybe_rules = marked_data.get("rules")
            if isinstance(maybe_rules, list):
                rules = [dict(one) for one in maybe_rules if isinstance(one, dict)]

        console_payload = {
            "submission_id": submission_id,
            "rules": rules,
            "marked_attachments": marked_data,
        }

        print(f"[LMS] marked_attachments mapping for submission {submission_id}")
        print(json.dumps(console_payload, ensure_ascii=False, indent=2))

    @pyqtSlot(dict)
    def show_video_page(self, video_info: dict):
        """展示课程回放视频播放页。"""
        play_url = str(video_info.get("download_url") or "").strip() if isinstance(video_info, dict) else ""
        if not play_url:
            self.error(self.tr("无法播放"), self.tr("该回放没有可用的在线播放链接"), parent=self)
            return

        video_label = format_replay_video_label(video_info.get("label"))
        breadcrumb_label = video_label if video_label != "-" else self.tr("在线查看")
        self.videoPage.setReplayVideo(video_info, self.selected_activity_name)
        self.navigate_to(self.videoPage, breadcrumb_label)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        """处理账号切换，清空状态并回到起始页。

        :return: 无返回值。
        """
        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_submission = None
        self._current_activities = []
        self._course_cache_visible_during_refresh = False
        self._activity_cache_visible_during_refresh = False
        self._preview_pixmap_cache.clear()
        self._mark_overlay_cache.clear()
        self._submission_marked_attachment_cache.clear()
        if self._preview_dialog is not None:
            self._preview_dialog.close()

        self.coursePage.reset()
        self.activityPage.reset()
        self.detailPage.reset()
        self.submissionPage.reset()
        self.videoPage.reset()
        self.startPage.reset()

        self._initBreadcrumbRoot(switch_page=False)
        self.switchPage(self.startPage)

    def _open_file(self, file_info: dict):
        """使用系统浏览器打开文件预览链接。"""
        url = file_info.get("preview_url") or file_info.get("download_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法查看"), self.tr("该文件没有可用链接"), parent=self)
            return
        current_account = accounts.current
        if current_account is not None:
            try:
                access_mode = current_account.session_manager.resolve_access_mode()
                if access_mode == AccessMode.WEBVPN and url.startswith(("http://", "https://")):
                    url = getVPNUrl(url)
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot(dict)
    def _save_file(self, file_info: dict):
        """执行文件另存为并启动下载线程。"""
        url = file_info.get("download_url") or file_info.get("preview_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法下载"), self.tr("该文件没有可用下载链接"), parent=self)
            return

        suggested_name = self.build_default_filename(file_info)
        default_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        default_path = os.path.join(default_dir, suggested_name)

        path, ok = QFileDialog.getSaveFileName(self, self.tr("保存附件"), default_path, self.tr("所有文件 (*)"))
        if not ok or not path:
            return

        try:
            current_account = accounts.current
            if current_account is None:
                self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
                return
            session, error = self.ensure_lms_login()
            if session is None:
                self.error(self.tr("未登录"), error or self.tr("请先添加一个账户"), parent=self)
                return
            bar = ProgressInfoBar(title=self.tr("附件下载"), content=self.tr("准备下载"), parent=self,
                                  position=InfoBarPosition.BOTTOM_RIGHT)
            thread = LMSFileDownloadThread(session, url, path, os.path.basename(path), parent=self)
            bar.connectToThread(thread)
            thread.error.connect(lambda title, msg: self.error(title, msg, parent=self))
            thread.hasFinished.connect(lambda: self.success(self.tr("下载成功"), self.tr("已保存到：{0}").format(path), parent=self))

            self._download_jobs.append((bar, thread))
            thread.finished.connect(lambda: self._cleanup_download_job(bar, thread))
            thread.canceled.connect(lambda: self._cleanup_download_job(bar, thread))

            bar.show()
            thread.start()
        except Exception as e:
            self.error(self.tr("下载失败"), str(e), parent=self)

    def _cleanup_download_job(self, bar: ProgressInfoBar, thread: LMSFileDownloadThread):
        """清理已结束或取消的下载任务引用。"""
        self._download_jobs = [one for one in self._download_jobs if one != (bar, thread)]

    @pyqtSlot(dict, list)
    def show_attachment_preview(self, file_info: dict, uploads: list):
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        self._preview_image_file(file_info, rows)

    @pyqtSlot(dict, list, list)
    def show_attachment_review_preview(self, file_info: dict, uploads: list, review_uploads: list):
        original_rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        if isinstance(self._current_submission, dict):
            self._ensure_submission_marked_attachments_loaded(self._current_submission, force=True)
            submission_uploads = self._current_submission.get("uploads", [])
            if isinstance(submission_uploads, list):
                uploads = submission_uploads
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        marked_data = self._current_submission.get("marked_attachments") if isinstance(self._current_submission, dict) else None
        review_rows = self._build_review_preview_rows(rows, marked_data)
        if not review_rows:
            self.error(self.tr("批改预览不可用"), self.tr("当前提交中没有可预览图片"), parent=self)
            return

        original_image_rows = [one for one in original_rows if can_preview_as_image(one)]
        clicked_index = self._find_upload_index(file_info, original_image_rows)
        if clicked_index is None:
            clicked_index = self._find_upload_index(file_info, review_rows)
        if clicked_index is not None and 0 <= clicked_index < len(review_rows):
            file_info = review_rows[clicked_index]
        else:
            matched_file_info = self._find_matching_upload_row(file_info, review_rows)
            if matched_file_info is not None:
                file_info = matched_file_info

        self._preview_image_file(file_info, review_rows, True, review_rows)

    @staticmethod
    def _as_float(value) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _preview_key(self, file_info: dict) -> str:
        download_url = str(file_info.get("download_url") or "")
        preview_url = str(file_info.get("preview_url") or "")
        attachment_url = str(file_info.get("attachment_url") or "")
        reference_id = str(file_info.get("reference_id") or "")
        upload_id = str(file_info.get("id") or "")
        return f"{upload_id}|{reference_id}|{download_url}|{preview_url}|{attachment_url}"

    def _extract_nested_url(self, payload) -> str | None:
        if isinstance(payload, str):
            text = payload.strip().strip('"').strip("'")
            if text.startswith("http://") or text.startswith("https://"):
                return text
            if text and text[0] in "{[":
                try:
                    parsed = json.loads(text)
                except Exception:
                    return None
                return self._extract_nested_url(parsed)
            return None

        if isinstance(payload, dict):
            for key in ("url", "download_url", "preview_url", "attachment_url", "signed_url", "src", "href", "link"):
                result = self._extract_nested_url(payload.get(key))
                if result:
                    return result
            for value in payload.values():
                result = self._extract_nested_url(value)
                if result:
                    return result
            return None

        if isinstance(payload, list):
            for value in payload:
                result = self._extract_nested_url(value)
                if result:
                    return result
        return None

    def _resolve_upload_urls(self, file_info: dict) -> list[str]:
        urls: list[str] = []
        prefer_preview = bool(file_info.get("_prefer_preview_url_first"))
        prefer_attachment = bool(file_info.get("_prefer_attachment_url_first"))
        ordered_keys = (
            ("attachment_url", "preview_url", "download_url", "url", "href")
            if prefer_attachment else
            ("preview_url", "download_url", "attachment_url", "url", "href")
            if prefer_preview else
            ("download_url", "preview_url", "attachment_url", "url", "href")
        )
        for key in ordered_keys:
            value = file_info.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in urls:
                urls.append(value)

        nested = self._extract_nested_url(file_info)
        if nested and nested not in urls:
            urls.append(nested)
        return urls

    def _fetch_text_payload(self, file_info: dict) -> tuple[str | None, str | None]:
        if accounts.current is None:
            return None, self.tr("请先登录后再预览")

        session, error = self.ensure_lms_login()
        if session is None:
            return None, error

        queue = self._resolve_upload_urls(file_info)
        tried: set[str] = set()
        errors: list[str] = []

        while queue and len(tried) < 12:
            url = queue.pop(0)
            if not isinstance(url, str) or not url or url in tried:
                continue
            tried.add(url)

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except Exception as e:
                errors.append(str(e))
                continue

            data = response.content or b""
            content_type = str(response.headers.get("Content-Type") or "").lower()
            nested_url = None
            text = None

            if "json" in content_type:
                try:
                    payload = response.json()
                    text = json.dumps(payload, ensure_ascii=False)
                    nested_url = self._extract_nested_url(payload)
                except Exception:
                    text = None

            binary_like = (
                content_type.startswith("image/")
                or content_type.startswith("video/")
                or content_type.startswith("audio/")
                or "octet-stream" in content_type
                or "application/pdf" in content_type
            )

            if text is None and data:
                encodings = ["utf-8-sig", "utf-8", "gb18030"]
                if content_type.startswith("text/"):
                    encodings.append("latin-1")
                for encoding in encodings:
                    try:
                        text = data.decode(encoding)
                        break
                    except Exception:
                        continue
                if text:
                    nested_url = nested_url or self._extract_nested_url(text[:4096])

            if nested_url and nested_url not in tried and nested_url not in queue:
                queue.append(nested_url)
                if text and len(text.strip()) < 2048 and text.strip().startswith(("http://", "https://", "{", "[")):
                    continue

            if (not binary_like) and text and text.strip():
                return text, None

        reason = errors[-1] if errors else self.tr("无法读取批改标注文件")
        return None, reason

    def _extract_mark_overlay_items(self, payload) -> list[dict]:
        items: list[dict] = []
        page_container_keys = {"pages", "images", "attachments", "files", "canvases", "slides"}
        id_keys = (
            "id", "upload_id", "uploadId", "target_id", "targetId", "image_id", "imageId", "origin_upload_id",
            "originUploadId"
        )
        reference_id_keys = ("reference_id", "referenceId", "file_id", "fileId", "origin_reference_id", "originReferenceId")
        key_keys = ("key", "upload_key", "uploadKey", "file_key", "fileKey")

        def normalize_token(value) -> str:
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return str(value or "").strip().lower()

        def add_prefixed_token(kind: str, raw, tokens: set[str]):
            if raw is None:
                return
            if isinstance(raw, (int, float)):
                token_value = normalize_token(raw)
                if token_value:
                    tokens.add(f"{kind}:{token_value}")
                return
            if isinstance(raw, str):
                token_value = normalize_token(raw)
                if token_value:
                    tokens.add(f"{kind}:{token_value}")
                return
            if isinstance(raw, dict):
                add_tokens_from_mapping(raw, tokens)
                return
            if isinstance(raw, (list, tuple)):
                for one in raw[:12]:
                    add_prefixed_token(kind, one, tokens)

        def add_tokens_from_mapping(raw: dict, tokens: set[str]):
            for key in id_keys:
                add_prefixed_token("id", raw.get(key), tokens)
            for key in reference_id_keys:
                add_prefixed_token("reference_id", raw.get(key), tokens)
            for key in key_keys:
                add_prefixed_token("key", raw.get(key), tokens)
            for nested_key in (
                "upload",
                "origin_upload", "originUpload",
                "origin_attachment", "originAttachment",
                "source_upload", "sourceUpload",
                "source_attachment", "sourceAttachment",
                "attachment",
                "origin",
                "source",
                "file",
                "image",
            ):
                nested_value = raw.get(nested_key)
                if isinstance(nested_value, dict):
                    add_tokens_from_mapping(nested_value, tokens)
                elif isinstance(nested_value, (list, tuple)):
                    for one in nested_value[:12]:
                        if isinstance(one, dict):
                            add_tokens_from_mapping(one, tokens)

        def collect_target_tokens(node) -> set[str]:
            if not isinstance(node, dict):
                return set()
            tokens: set[str] = set()
            add_tokens_from_mapping(node, tokens)
            return {one for one in tokens if one}

        def parse_unit_hint(node, inherited: str | None) -> str | None:
            if not isinstance(node, dict):
                return inherited
            for key in (
                "coord_unit", "coordUnit", "coordinate_unit", "coordinateUnit",
                "coordinate_type", "coordinateType", "coord_type", "coordType", "unit"
            ):
                value = node.get(key)
                if not isinstance(value, str):
                    continue
                text = value.strip().lower()
                if not text:
                    continue
                if "percent" in text or text in {"%", "pct"}:
                    return "percent"
                if "ratio" in text or "normalized" in text or "relative" in text:
                    return "ratio"
                if "pixel" in text or text in {"px", "pixels"}:
                    return "px"
            return inherited

        def parse_page_hint(node, inherited: int | None) -> int | None:
            if not isinstance(node, dict):
                return inherited
            for key in ("page_index", "pageIndex", "image_index", "imageIndex", "img_index", "imgIndex", "page"):
                value = self._as_float(node.get(key))
                if value is None:
                    continue
                return int(round(value))
            return inherited

        def parse_dimension_hints(node, inherited_w: float | None, inherited_h: float | None) -> tuple[float | None, float | None]:
            width = inherited_w
            height = inherited_h
            if not isinstance(node, dict):
                return width, height

            for w_key, h_key in (
                ("image_width", "image_height"),
                ("imageWidth", "imageHeight"),
                ("img_width", "img_height"),
                ("imgWidth", "imgHeight"),
                ("origin_width", "origin_height"),
                ("originWidth", "originHeight"),
                ("original_width", "original_height"),
                ("originalWidth", "originalHeight"),
                ("natural_width", "natural_height"),
                ("naturalWidth", "naturalHeight"),
                ("canvas_width", "canvas_height"),
                ("canvasWidth", "canvasHeight"),
                ("page_width", "page_height"),
                ("pageWidth", "pageHeight"),
                ("display_width", "display_height"),
                ("displayWidth", "displayHeight"),
                ("source_width", "source_height"),
                ("sourceWidth", "sourceHeight"),
                ("base_width", "base_height"),
                ("baseWidth", "baseHeight"),
            ):
                w = self._as_float(node.get(w_key))
                h = self._as_float(node.get(h_key))
                if w is not None and h is not None and w > 0 and h > 0:
                    return w, h

            for size_key in (
                "size", "image_size", "imageSize", "origin_size", "originSize",
                "original_size", "originalSize", "natural_size", "naturalSize",
                "canvas_size", "canvasSize", "page_size", "pageSize",
                "display_size", "displaySize", "source_size", "sourceSize"
            ):
                size = node.get(size_key)
                if not isinstance(size, dict):
                    continue
                for w_key, h_key in (("width", "height"), ("w", "h"), ("imageWidth", "imageHeight")):
                    w = self._as_float(size.get(w_key))
                    h = self._as_float(size.get(h_key))
                    if w is not None and h is not None and w > 0 and h > 0:
                        return w, h

            return width, height

        def apply_box_values(
            values,
            *,
            prefer_xyxy: bool = False,
            current_x: float | None = None,
            current_y: float | None = None,
            current_w: float | None = None,
            current_h: float | None = None,
        ) -> tuple[float | None, float | None, float | None, float | None]:
            if not isinstance(values, (list, tuple)) or len(values) < 4:
                return current_x, current_y, current_w, current_h

            v1 = self._as_float(values[0])
            v2 = self._as_float(values[1])
            v3 = self._as_float(values[2])
            v4 = self._as_float(values[3])

            x = current_x if current_x is not None else v1
            y = current_y if current_y is not None else v2
            w = current_w
            h = current_h

            treat_as_xyxy = prefer_xyxy
            if not treat_as_xyxy and None not in (v1, v2, v3, v4):
                treat_as_xyxy = (v3 >= v1 and v4 >= v2 and (v3 > 1 or v4 > 1))

            if treat_as_xyxy:
                if x is not None and w is None and v3 is not None:
                    w = v3 - x
                if y is not None and h is None and v4 is not None:
                    h = v4 - y
            else:
                if w is None:
                    w = v3
                if h is None:
                    h = v4

            return x, y, w, h

        def append_item(
            item: dict,
            context_tokens: set[str],
            context_w: float | None,
            context_h: float | None,
            context_page: int | None,
            context_unit: str | None,
        ):
            if context_tokens:
                item["targets"] = sorted(context_tokens)[:24]
            if context_w is not None and context_w > 0:
                item["base_w"] = context_w
            if context_h is not None and context_h > 0:
                item["base_h"] = context_h
            if context_page is not None:
                item["page_index"] = context_page
            if context_unit:
                item["coord_unit"] = context_unit
            items.append(item)

        def walk(
            node,
            context_tokens: set[str] | None = None,
            context_w: float | None = None,
            context_h: float | None = None,
            context_page: int | None = None,
            context_unit: str | None = None,
            parent_key: str | None = None,
        ):
            inherited_tokens = set(context_tokens or set())

            if isinstance(node, dict):
                local_tokens = inherited_tokens | collect_target_tokens(node)
                local_w, local_h = parse_dimension_hints(node, context_w, context_h)
                local_page = parse_page_hint(node, context_page)
                local_unit = parse_unit_hint(node, context_unit)

                text = ""
                for key in ("text", "comment", "content", "remark", "label", "note", "msg", "message"):
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break

                x = self._as_float(node.get("x"))
                y = self._as_float(node.get("y"))
                w = self._as_float(node.get("w"))
                h = self._as_float(node.get("h"))
                if x is None:
                    x = self._as_float(node.get("x1"))
                if y is None:
                    y = self._as_float(node.get("y1"))
                if x is None:
                    x = self._as_float(node.get("left"))
                if y is None:
                    y = self._as_float(node.get("top"))
                if w is None:
                    w = self._as_float(node.get("width"))
                if h is None:
                    h = self._as_float(node.get("height"))

                right = self._as_float(node.get("right"))
                bottom = self._as_float(node.get("bottom"))
                x2 = self._as_float(node.get("x2"))
                y2 = self._as_float(node.get("y2"))
                if right is not None:
                    x2 = right if x2 is None else x2
                if bottom is not None:
                    y2 = bottom if y2 is None else y2
                if x is not None and w is None and x2 is not None:
                    w = x2 - x
                if y is not None and h is None and y2 is not None:
                    h = y2 - y
                if x is None and x2 is not None and w is not None:
                    x = x2 - w
                if y is None and y2 is not None and h is not None:
                    y = y2 - h

                rect = node.get("rect")
                if isinstance(rect, (list, tuple)) and len(rect) >= 4:
                    x, y, w, h = apply_box_values(rect, current_x=x, current_y=y, current_w=w, current_h=h)
                elif isinstance(rect, dict):
                    rect_x1 = self._as_float(rect.get("x1"))
                    rect_y1 = self._as_float(rect.get("y1"))
                    rect_x2 = self._as_float(rect.get("x2"))
                    rect_y2 = self._as_float(rect.get("y2"))
                    x = self._as_float(rect.get("x")) if x is None else x
                    y = self._as_float(rect.get("y")) if y is None else y
                    if x is None:
                        x = rect_x1
                    if y is None:
                        y = rect_y1
                    if x is None:
                        x = self._as_float(rect.get("left"))
                    if y is None:
                        y = self._as_float(rect.get("top"))
                    if w is None:
                        w = self._as_float(rect.get("w"))
                    if h is None:
                        h = self._as_float(rect.get("h"))
                    if w is None:
                        w = self._as_float(rect.get("width"))
                    if h is None:
                        h = self._as_float(rect.get("height"))
                    if x is not None and w is None:
                        right_value = rect_x2 if rect_x2 is not None else self._as_float(rect.get("right"))
                        if right_value is not None:
                            w = right_value - x
                    if y is not None and h is None:
                        bottom_value = rect_y2 if rect_y2 is not None else self._as_float(rect.get("bottom"))
                        if bottom_value is not None:
                            h = bottom_value - y

                bbox = node.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x, y, w, h = apply_box_values(
                        bbox, prefer_xyxy=True, current_x=x, current_y=y, current_w=w, current_h=h
                    )
                elif isinstance(bbox, dict):
                    bbox_x1 = self._as_float(bbox.get("x1"))
                    bbox_y1 = self._as_float(bbox.get("y1"))
                    bbox_x2 = self._as_float(bbox.get("x2"))
                    bbox_y2 = self._as_float(bbox.get("y2"))
                    x = bbox_x1 if x is None else x
                    y = bbox_y1 if y is None else y
                    if w is None:
                        w = self._as_float(bbox.get("w"))
                    if h is None:
                        h = self._as_float(bbox.get("h"))
                    if x is not None and w is None and bbox_x2 is not None:
                        w = bbox_x2 - x
                    if y is not None and h is None and bbox_y2 is not None:
                        h = bbox_y2 - y

                graphic = node.get("graphic")
                has_graphic_path = False
                if isinstance(graphic, dict):
                    path = graphic.get("path")
                    if isinstance(path, list) and path:
                        has_graphic_path = True
                        append_item(
                            {
                                "path": path,
                                "text": text,
                                "color": graphic.get("borderColor") or node.get("borderColor"),
                                "border_width": self._as_float(graphic.get("borderWidth")) or self._as_float(node.get("borderWidth")),
                            },
                            local_tokens,
                            local_w,
                            local_h,
                            local_page,
                            local_unit,
                        )
                    if x is None:
                        x = self._as_float(graphic.get("left"))
                    if y is None:
                        y = self._as_float(graphic.get("top"))
                    if w is None:
                        w = self._as_float(graphic.get("width"))
                    if h is None:
                        h = self._as_float(graphic.get("height"))

                should_append_xy_item = x is not None and y is not None
                if has_graphic_path and w is None and h is None and not text:
                    should_append_xy_item = False

                if should_append_xy_item:
                    append_item(
                        {
                            "x": x, "y": y, "w": w, "h": h, "text": text,
                            "color": node.get("borderColor"), "border_width": self._as_float(node.get("borderWidth")),
                        },
                        local_tokens,
                        local_w,
                        local_h,
                        local_page,
                        local_unit,
                    )

                for key, value in node.items():
                    if isinstance(value, list) and key in page_container_keys and local_page is None:
                        for i, one in enumerate(value):
                            walk(one, local_tokens, local_w, local_h, i, local_unit, key)
                    else:
                        walk(value, local_tokens, local_w, local_h, local_page, local_unit, key)
                return

            if isinstance(node, list):
                for i, value in enumerate(node):
                    page_hint = context_page
                    if parent_key in page_container_keys and page_hint is None:
                        page_hint = i
                    walk(value, inherited_tokens, context_w, context_h, page_hint, context_unit, parent_key)

        walk(payload)
        return items[:200]

    def _extract_mark_summary_text(self, payload) -> str | None:
        texts: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for key in ("text", "comment", "content", "remark", "label", "note", "msg", "message"):
                    value = node.get(key)
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped:
                            texts.append(stripped)
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        if not texts:
            return None
        return "\n".join(texts[:10])

    def _iter_mark_payload_candidates(self, payload) -> list:
        candidates: list = []
        seen: set[str] = set()

        def remember(node) -> bool:
            try:
                marker = json.dumps(node, ensure_ascii=False, sort_keys=True, default=str)
            except Exception:
                marker = repr(node)
            if marker in seen:
                return False
            seen.add(marker)
            candidates.append(node)
            return True

        def walk(node, depth: int = 0):
            if depth > 5:
                return
            if not remember(node):
                return

            if isinstance(node, str):
                text = node.strip()
                if not text:
                    return
                variants = [text]
                try:
                    decoded = unquote(text)
                    if decoded and decoded != text:
                        variants.append(decoded)
                        decoded_twice = unquote(decoded)
                        if decoded_twice and decoded_twice != decoded:
                            variants.append(decoded_twice)
                except Exception:
                    pass

                for variant in variants:
                    compact = variant.strip()
                    if not compact:
                        continue
                    if compact[:1] in {'{', '[', '"'}:
                        try:
                            walk(json.loads(compact), depth + 1)
                        except Exception:
                            continue
                return

            if isinstance(node, dict):
                for key in (
                    "data", "payload", "result", "content", "annotation", "annotations",
                    "mark", "marks", "markup", "items", "list"
                ):
                    if key in node:
                        walk(node.get(key), depth + 1)
                for value in node.values():
                    if isinstance(value, (dict, list, str)):
                        walk(value, depth + 1)
                return

            if isinstance(node, list):
                for value in node[:50]:
                    if isinstance(value, (dict, list, str)):
                        walk(value, depth + 1)

        walk(payload)
        return candidates

    def _parse_mark_attachment_text(self, text: str) -> tuple[str | None, list[dict]]:
        content = (text or "").strip()
        if not content:
            return None, []

        for one in self._iter_mark_payload_candidates(content):
            if isinstance(one, (dict, list)):
                items = self._extract_mark_overlay_items(one)
                summary = self._extract_mark_summary_text(one)
                if summary or items:
                    return summary, items

        items: list[dict] = []
        line_re = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[:：\-]\s*(.+?)\s*$")
        for line in content.splitlines():
            match = line_re.match(line)
            if not match:
                continue
            x = self._as_float(match.group(1))
            y = self._as_float(match.group(2))
            msg = match.group(3).strip()
            if x is not None and y is not None:
                items.append({"x": x, "y": y, "text": msg, "shape": "point"})

        summary_lines = [one.strip() for one in content.splitlines() if one.strip()][:10]
        summary = "\n".join(summary_lines) if summary_lines else None
        return summary, items

    @staticmethod
    def _extract_inline_mark_payload(upload: dict):
        for key in (
            "marked_attachment_payload",
            "marked_attachments_payload",
            "marked_attachments",
            "mark_overlay_payload",
            "overlay_payload",
            "annotation_payload",
            "annotations",
            "annotation",
            "mark_data",
            "markup",
            "payload",
            "data",
        ):
            if key in upload:
                value = upload.get(key)
                if value is not None:
                    return value
        return None

    @staticmethod
    def _has_explicit_mark_binding(file_info: dict | None) -> bool:
        if not isinstance(file_info, dict):
            return False
        if "marked_attachment_payload" in file_info:
            return True
        attachment_url = file_info.get("attachment_url")
        return isinstance(attachment_url, str) and bool(attachment_url)

    @staticmethod
    def _overlay_items_match_file(items: list[dict], file_info: dict | None) -> bool:
        if not isinstance(file_info, dict) or not items:
            return False
        file_tokens = LMSImagePreviewDialog._collect_file_tokens(file_info)
        if not file_tokens:
            return False
        for item in items[:300]:
            if not isinstance(item, dict):
                continue
            item_tokens = LMSImagePreviewDialog._collect_overlay_item_tokens(item)
            if item_tokens and (not file_tokens.isdisjoint(item_tokens)):
                return True
        return False

    @staticmethod
    def _review_row_matches_file(row: dict | None, file_info: dict | None) -> bool:
        if not isinstance(row, dict) or not isinstance(file_info, dict):
            return False

        row_tokens = LMSImagePreviewDialog._collect_file_tokens(row)
        file_tokens = LMSImagePreviewDialog._collect_file_tokens(file_info)
        if row_tokens and file_tokens and (not row_tokens.isdisjoint(file_tokens)):
            return True

        for key in ("attachment_url", "preview_url", "download_url"):
            row_value = row.get(key)
            file_value = file_info.get(key)
            if isinstance(row_value, str) and isinstance(file_value, str) and row_value and row_value == file_value:
                return True
        return False

    def _extract_mark_page_hints(self, payload) -> set[int]:
        hints: set[int] = set()

        def walk(node):
            if isinstance(node, dict):
                for key in ("page_index", "pageIndex", "image_index", "imageIndex", "img_index", "imgIndex", "page"):
                    value = self._as_float(node.get(key))
                    if value is not None:
                        rounded = int(round(value))
                        hints.add(rounded)
                        if rounded > 0:
                            hints.add(rounded - 1)
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return {one for one in hints if one >= 0}

    @staticmethod
    def _filter_overlay_items_by_page_hints(items: list[dict], page_hints: set[int]) -> list[dict]:
        if not items or not page_hints:
            return items

        filtered: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_page = item.get("page_index")
            try:
                if raw_page is None:
                    continue
                page_index = int(round(float(raw_page)))
            except (TypeError, ValueError):
                continue
            if page_index in page_hints:
                filtered.append(item)
        return filtered

    def _parse_mark_attachment_payload(self, payload) -> tuple[str | None, list[dict]]:
        if payload is None:
            return None, []
        for one in self._iter_mark_payload_candidates(payload):
            if isinstance(one, (dict, list)):
                summary = self._extract_mark_summary_text(one)
                items = self._extract_mark_overlay_items(one)
                if summary or items:
                    return summary, items
        if isinstance(payload, str):
            return self._parse_mark_attachment_text(payload)
        try:
            dumped = json.dumps(payload, ensure_ascii=False)
        except Exception:
            return None, []
        return self._parse_mark_attachment_text(dumped)

    def _format_overlay_text(self, summary: str | None, items: list[dict], raw_text: str | None = None) -> str | None:
        if summary:
            return summary
        if items:
            return self.tr("已加载批改标注（无文字说明）")
        if raw_text:
            trimmed = raw_text.strip()
            if trimmed:
                return (trimmed[:800] + "...") if len(trimmed) > 800 else trimmed
        return None

    def _has_review_overlay_source(self, uploads: list[dict]) -> bool:
        for one in uploads:
            if not isinstance(one, dict):
                continue
            review_attachment_url = one.get("_review_attachment_url")
            if isinstance(review_attachment_url, str) and review_attachment_url.startswith(("http://", "https://")):
                return True
            if self._extract_inline_mark_payload(one) is not None:
                return True
            attachment_url = one.get("attachment_url")
            if isinstance(attachment_url, str) and attachment_url.startswith(("http://", "https://")):
                return True
            if is_mark_attachment_upload(one):
                return True
        return False

    def _get_review_overlay_data_v2(self, uploads: list[dict], current_file: dict | None = None) -> tuple[str | None, list[dict], str | None]:
        if not isinstance(current_file, dict):
            return None, [], self.tr("当前图片没有对应批注")

        attachment_url = current_file.get("_review_attachment_url")
        if not isinstance(attachment_url, str) or not attachment_url:
            attachment_url = current_file.get("attachment_url")
        if (not isinstance(attachment_url, str) or not attachment_url) and isinstance(uploads, list):
            matched_row = self._find_matching_upload_row(current_file, [one for one in uploads if isinstance(one, dict)])
            if matched_row is None:
                for one in uploads:
                    if isinstance(one, dict) and self._review_row_matches_file(one, current_file):
                        matched_row = one
                        break
            if isinstance(matched_row, dict):
                matched_attachment_url = matched_row.get("_review_attachment_url")
                if not isinstance(matched_attachment_url, str) or not matched_attachment_url:
                    matched_attachment_url = matched_row.get("attachment_url")
                if isinstance(matched_attachment_url, str) and matched_attachment_url:
                    attachment_url = matched_attachment_url
                    current_file = dict(current_file)
                    current_file["_review_attachment_url"] = matched_attachment_url

        if not isinstance(attachment_url, str) or not attachment_url:
            return None, [], self.tr("当前图片没有对应批注")

        text_source = {
            "attachment_url": attachment_url,
            "_prefer_attachment_url_first": True,
            "name": current_file.get("name"),
        }
        cache_key = f"attachment-direct-v3|{self._preview_key(text_source)}"
        if cache_key in self._mark_overlay_cache:
            overlay_text, items = self._mark_overlay_cache[cache_key]
        else:
            raw_text, error_text = self._fetch_text_payload(text_source)
            if not raw_text:
                return None, [], (error_text or self.tr("无法读取批注文件"))
            summary, items = self._parse_mark_attachment_text(raw_text)
            overlay_text = self._format_overlay_text(summary, items, raw_text)
            self._mark_overlay_cache[cache_key] = (overlay_text, items)

        if overlay_text or items:
            return overlay_text, items, None
        return None, [], self.tr("当前图片没有对应批注")

    @staticmethod
    def _normalize_review_rule_name(name: object) -> str:
        text = unquote(str(name or "")).strip().lower()
        if not text:
            return ""
        return re.sub(r"\s+", " ", text)

    @staticmethod
    def _extract_marked_attachment_url_from_rule(info: dict) -> str | None:
        if not isinstance(info, dict):
            return None

        containers = []
        marked_attachment = info.get("marked_attachment")
        if isinstance(marked_attachment, dict):
            containers.append(marked_attachment)
            nested_upload = marked_attachment.get("upload")
            if isinstance(nested_upload, dict):
                containers.append(nested_upload)
        containers.append(info)

        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("url", "download_url", "preview_url", "attachment_url", "signed_url", "href", "link"):
                value = container.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
        return None

    def _extract_marked_attachment_rules(self, marked_data: dict | None) -> list[dict]:
        if not isinstance(marked_data, dict):
            return []

        rules: list[dict] = []
        raw_rules = marked_data.get("rules")
        if not isinstance(raw_rules, list):
            return []
        for index, rule in enumerate(raw_rules):
            if not isinstance(rule, dict):
                continue
            origin_name = rule.get("origin_upload_name") or rule.get("origin_name") or rule.get("name")
            marked_attachment_url = rule.get("url") or rule.get("marked_attachment_url")
            normalized_origin_name = self._normalize_review_rule_name(origin_name)
            if not normalized_origin_name or not marked_attachment_url:
                continue
            rules.append({
                "index": index,
                "origin_name": str(origin_name),
                "normalized_origin_name": normalized_origin_name,
                "marked_attachment_url": marked_attachment_url,
            })
        return rules

    def _build_review_preview_rows(self, uploads: list[dict], marked_data: dict | None) -> list[dict]:
        image_rows = [dict(one) for one in uploads if isinstance(one, dict) and can_preview_as_image(one)]
        if not image_rows:
            return []

        grouped_rules: dict[str, list[dict]] = defaultdict(list)
        for rule in self._extract_marked_attachment_rules(marked_data):
            grouped_rules[rule["normalized_origin_name"]].append(rule)

        usage_counter: dict[str, int] = defaultdict(int)
        prepared_rows: list[dict] = []
        for row in image_rows:
            prepared = dict(row, _prefer_preview_url_first=True)
            if prepared.get("preview_url"):
                prepared.pop("download_url", None)

            normalized_name = self._normalize_review_rule_name(prepared.get("name"))
            occurrence_index = usage_counter[normalized_name]
            usage_counter[normalized_name] += 1

            prepared["_review_name_key"] = normalized_name
            prepared["_review_name_index"] = occurrence_index

            rule_bucket = grouped_rules.get(normalized_name, [])
            if occurrence_index < len(rule_bucket):
                rule = rule_bucket[occurrence_index]
                prepared["_review_attachment_url"] = rule.get("marked_attachment_url")
                prepared["_review_rule_index"] = rule.get("index")

            prepared_rows.append(prepared)

        return prepared_rows

    def _load_review_overlay_into_dialog(self, selected_key: str, review_rows: list[dict], current_file: dict):
        overlay_text, overlay_items, overlay_error = self._get_review_overlay_data_v2(review_rows, current_file=current_file)
        dialog = self._preview_dialog
        if dialog is None:
            return

        active_file = getattr(dialog, "_current_preview_file", None)
        if self._preview_key(active_file) != selected_key:
            return

        if overlay_error:
            dialog.set_overlay_content(None, [])
            self.error(self.tr("批改预览不可用"), overlay_error, parent=self)
            return

        dialog.set_overlay_content(overlay_text, overlay_items)

    def _fetch_image_pixmap(self, file_info: dict) -> tuple[QPixmap | None, str | None]:
        if accounts.current is None:
            return None, self.tr("请先登录后再预览")

        session, error = self.ensure_lms_login()
        if session is None:
            return None, error

        queue = self._resolve_upload_urls(file_info)
        tried: set[str] = set()
        errors: list[str] = []

        while queue and len(tried) < 12:
            url = queue.pop(0)
            if not isinstance(url, str) or not url or url in tried:
                continue
            tried.add(url)

            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except Exception as e:
                errors.append(str(e))
                continue

            content = response.content or b""
            if content:
                buffer = QBuffer()
                buffer.setData(content)
                buffer.open(QBuffer.ReadOnly)
                image_reader = QImageReader(buffer)
                # Respect EXIF orientation so phone photos display with correct rotation.
                image_reader.setAutoTransform(True)
                loaded_image = image_reader.read()
                if not loaded_image.isNull():
                    pixmap = QPixmap.fromImage(loaded_image)
                    return pixmap, None

            nested_url = None
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "json" in content_type:
                try:
                    nested_url = self._extract_nested_url(response.json())
                except Exception:
                    nested_url = self._extract_nested_url(content[:4096].decode("utf-8", errors="ignore"))
            elif content:
                nested_url = self._extract_nested_url(content[:4096].decode("utf-8", errors="ignore"))

            if nested_url and nested_url not in tried and nested_url not in queue:
                queue.append(nested_url)

        reason = errors[-1] if errors else self.tr("文件不是可预览图片，或缺少有效图片链接")
        return None, reason

    def _get_cached_preview_pixmap(self, file_info: dict) -> tuple[QPixmap | None, str | None]:
        cache_key = self._preview_key(file_info)
        pixmap = self._preview_pixmap_cache.get(cache_key)
        if pixmap is not None and not pixmap.isNull():
            return pixmap, None

        pixmap, error_text = self._fetch_image_pixmap(file_info)
        if pixmap is not None and not pixmap.isNull():
            self._preview_pixmap_cache[cache_key] = pixmap
            return pixmap, None
        return None, error_text

    def _preview_image_file(
        self,
        file_info: dict,
        uploads: list[dict] | None = None,
        review_mode: bool = False,
        review_uploads: list[dict] | None = None,
    ):
        if not can_preview_as_image(file_info):
            self.error(self.tr("无法预览"), self.tr("该附件不是可预览图片"), parent=self)
            return

        if isinstance(uploads, list):
            image_rows = [one for one in uploads if isinstance(one, dict) and can_preview_as_image(one)]
        else:
            image_rows = [file_info]

        if not image_rows:
            self.error(self.tr("无法预览"), self.tr("当前列表没有可预览图片"), parent=self)
            return

        current_preview_file = file_info

        if review_mode:
            image_rows = [dict(one) for one in image_rows]
            current_preview_file = dict(file_info)

        selected_key = self._preview_key(current_preview_file)
        if self._preview_dialog is None:
            self._preview_dialog = LMSImagePreviewDialog(
                fetch_pixmap_callback=self._get_cached_preview_pixmap,
                preview_key_callback=self._preview_key,
                safe_text_callback=lambda value: str(value) if value not in (None, "") else "-",
                parent=self.window(),
            )

        overlay_text = None
        overlay_items: list[dict] | None = None
        overlay_loader_callback = None
        if review_mode:
            overlay_text = self.tr("正在加载批注...")
            review_rows = (
                [one for one in review_uploads if isinstance(one, dict)] if isinstance(review_uploads, list)
                else ([one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else [])
            )
            def overlay_loader_callback(current, rows=review_rows):
                self._load_review_overlay_into_dialog(self._preview_key(current), rows, dict(current))

        self._preview_dialog.open_images(
            image_rows,
            selected_key,
            overlay_text=overlay_text,
            overlay_items=overlay_items,
            review_mode=review_mode,
            overlay_loader_callback=overlay_loader_callback,
        )

    def _updateDetailBreadcrumbLabel(self, label: str):
        """更新详情页所在面包屑节点的文本。"""
        display_text = self._truncateBreadcrumbLabel(label)
        self.breadcrumbBar.setItemText(self.ROUTE_DETAIL, display_text)
        self.breadcrumbBar.updateGeometry()

    def _findRelatedLessonActivity(self, lesson_start_time: str) -> dict:
        """在当前课程已加载活动中根据开始时间查找对应回放 lesson。"""
        target_time_key = self._normalizeActivityTimeKey(lesson_start_time)
        for activity in self._current_activities:
            if not isinstance(activity, dict):
                continue
            if str(activity.get("type") or "") != ActivityType.LESSON.value:
                continue
            activity_time_key = self._normalizeActivityTimeKey(activity.get("start_time"))
            if activity_time_key == target_time_key:
                return activity
        return {}

    @staticmethod
    def _normalizeActivityTimeKey(value: object) -> str:
        """将活动时间标准化为稳定的比较键。"""
        if not isinstance(value, str) or not value:
            return ""

        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def format_size(size) -> str:
        """格式化文件大小为可读文本。

        :param size: 文件大小（字节）。
        :return: 格式化后的大小字符串。
        """
        return common_format_size(size)

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符。

        :param name: 原始文件名。
        :return: 清理后的安全文件名。
        """
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "attachment"

    @staticmethod
    def restore_mark_attachment_filename(name: str) -> str:
        text = str(name or "").strip()
        lowered = text.lower()
        for suffix in ("markattatchment.txt", "markattachment.txt"):
            if lowered == suffix:
                return suffix
            prefixed = f"_{suffix}"
            if lowered.endswith(prefixed):
                return suffix
        return text

    def build_default_filename(self, file_info: dict) -> str:
        """根据当前活动与文件信息生成默认保存文件名。

        :param file_info: 文件信息字典（包含 name/download_url/preview_url）。
        :return: 建议的保存文件名。
        """
        activity_title = self.selected_activity_name or "activity"
        raw_name = str(file_info.get("name") or "")
        download_url = str(file_info.get("download_url") or file_info.get("preview_url") or "")

        ext = ""
        if "." in raw_name and not raw_name.endswith("."):
            ext = "." + raw_name.split(".")[-1]
        elif download_url:
            path = unquote(urlparse(download_url).path)
            base = os.path.basename(path)
            if "." in base:
                ext = "." + base.split(".")[-1]

        base_name = raw_name
        # 对于下载回放做特殊命名
        if file_info.get("label"):
            label = file_info.get("label")
            if label == "INSTRUCTOR":
                base_name += "教室录像"
            elif label == "ENCODER":
                base_name += "电脑内录"

        if not base_name:
            base_name = "file"

        base_name = self.sanitize_filename(base_name)
        base_name = self.restore_mark_attachment_filename(base_name)
        title_name = self.sanitize_filename(activity_title)

        if ext and not base_name.lower().endswith(ext.lower()):
            base_name = f"{base_name}{ext}"

        if self.restore_mark_attachment_filename(raw_name).lower() in {"markattatchment.txt", "markattachment.txt"}:
            return base_name

        return f"{title_name}_{base_name}"
