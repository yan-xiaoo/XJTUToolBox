import os
import re
from typing import Optional
from urllib.parse import urlparse, unquote

from PyQt5.QtCore import pyqtSlot, Qt, QUrl, QStandardPaths
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QFileDialog, QSizePolicy
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, InfoBar, InfoBarPosition, BreadcrumbBar, \
    TransparentToolButton, FluentIcon

from .components.ProgressInfoBar import ProgressInfoBar
from .threads.LMSFileDownloadThread import LMSFileDownloadThread
from .threads.LMSThread import LMSThread, LMSAction
from .threads.ProcessWidget import ProcessWidget
from .utils import StyleSheet, accounts
from .sub_interfaces.lms import PageStatus, LMSStartPage, LMSCoursePage, LMSActivityPage, LMSDetailPage, LMSSubmissionPage
from .sub_interfaces.lms.common import format_size as common_format_size
from lms.models import ActivityType


class LMSInterface(ScrollArea):
    # 所有子页面的 ROUTE_KEY，用于在导航中标记页面。
    ROUTE_START = "startPage"
    ROUTE_COURSE = "coursePage"
    ROUTE_ACTIVITY = "activityPage"
    ROUTE_DETAIL = "detailPage"
    ROUTE_SUBMISSION = "submissionPage"

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
        self.contentLayout.addWidget(self.navFrame)

        self.pageHost = QWidget(self.view)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.pageLayout.setSpacing(0)
        self.contentLayout.addWidget(self.pageHost)

        self.thread_ = LMSThread()
        self.processWidget = ProcessWidget(self.thread_, self.view, stoppable=True, hide_on_end=True)
        self.processWidget.setVisible(False)
        self.contentLayout.addWidget(self.processWidget)
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
        """创建并挂载五个子页面。"""
        self.startPage = LMSStartPage(self)
        self.coursePage = LMSCoursePage(self)
        self.activityPage = LMSActivityPage(self)
        self.detailPage = LMSDetailPage(self)
        self.submissionPage = LMSSubmissionPage(self)

        self.pageLayout.addWidget(self.startPage)
        self.pageLayout.addWidget(self.coursePage)
        self.pageLayout.addWidget(self.activityPage)
        self.pageLayout.addWidget(self.detailPage)
        self.pageLayout.addWidget(self.submissionPage)

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
        self.submissionPage.downloadRequested.connect(self._save_file)

    def _initNavigationModel(self):
        """初始化页面与路由键的双向映射。"""
        self._page_route_map = {
            self.startPage: self.ROUTE_START,
            self.coursePage: self.ROUTE_COURSE,
            self.activityPage: self.ROUTE_ACTIVITY,
            self.detailPage: self.ROUTE_DETAIL,
            self.submissionPage: self.ROUTE_SUBMISSION,
        }
        self._route_page_map = {route: page for page, route in self._page_route_map.items()}

    def switchPage(self, page: QWidget):
        """切换当前显示页面并滚动回顶部。

        :param page: 目标页面对象（start/course/activity/detail/submission 之一）。
        :return: 无返回值。
        """
        self._current_page = page
        pages = (self.startPage, self.coursePage, self.activityPage, self.detailPage, self.submissionPage)
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
        self.setPageStatus(self._current_page, PageStatus.ERROR)

    @pyqtSlot()
    def refreshCourses(self):
        """触发课程列表异步加载。

        :return: 无返回值。
        """
        self.setPageStatus(self.coursePage, PageStatus.LOADING)
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
        self.setPageStatus(self.activityPage, PageStatus.LOADING)
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

        self.activityPage.setCurrentActivityType(ActivityType.HOMEWORK.value)
        self.activityPage.clearData()

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
        self.setPageStatus(self.coursePage, PageStatus.NORMAL)

        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_submission = None

        self.activityPage.reset()
        self.detailPage.reset()
        self.submissionPage.reset()

        self.coursePage.setCourses(courses)

        if courses:
            self.success(self.tr("加载完成"), self.tr("已获取 {0} 门课程").format(len(courses)), parent=self)
        else:
            self.success(self.tr("暂无课程"), self.tr("当前账号未获取到课程"), parent=self)

    @pyqtSlot(int, list)
    def onActivitiesLoaded(self, course_id: int, activities: list):
        """处理活动加载完成回调并下发到活动页。

        :param course_id: 返回数据所属的课程 ID。
        :param activities: 活动列表。
        :return: 无返回值。
        """
        self.setPageStatus(self.activityPage, PageStatus.NORMAL)
        if self.selected_course_id != course_id:
            return
        self.activityPage.setActivities(activities)
        self.switchPage(self.activityPage)
        if not activities:
            self.success(self.tr("无活动"), self.tr("该课程暂无可显示活动"), parent=self)

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
        self._current_submission = submission
        self.submissionPage.setSubmission(submission, self.selected_course_name, self.selected_activity_name)
        self.navigate_to(self.submissionPage, self.tr("提交详情"))

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

        self.coursePage.reset()
        self.activityPage.reset()
        self.detailPage.reset()
        self.submissionPage.reset()
        self.startPage.reset()

        self._initBreadcrumbRoot(switch_page=False)
        self.switchPage(self.startPage)

    def _open_file(self, file_info: dict):
        """使用系统浏览器打开文件预览链接。"""
        url = file_info.get("preview_url") or file_info.get("download_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法查看"), self.tr("该文件没有可用链接"), parent=self)
            return
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
            session = current_account.session_manager.get_session("lms")
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

        base_name = raw_name if raw_name else "file"
        base_name = self.sanitize_filename(base_name)
        title_name = self.sanitize_filename(activity_title)

        if ext and not base_name.lower().endswith(ext.lower()):
            base_name = f"{base_name}{ext}"

        return f"{title_name}_{base_name}"