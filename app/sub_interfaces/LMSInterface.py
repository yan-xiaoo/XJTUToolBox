import os
import re
from urllib.parse import urlparse, unquote

from PyQt5.QtCore import pyqtSlot, Qt, QUrl, QStandardPaths, QTimer
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QHeaderView, QTableWidgetItem, \
    QFileDialog, QLabel, QSizePolicy
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, PrimaryPushButton, PushButton, TableWidget, \
    InfoBar, InfoBarPosition, CaptionLabel, BodyLabel, isDarkTheme, Pivot, IndeterminateProgressBar

from ..components.ProgressInfoBar import ProgressInfoBar, ProgressBarThread
from ..threads.LMSThread import LMSThread, LMSAction
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet, accounts


class LMSFileDownloadThread(ProgressBarThread):
    def __init__(self, session, url: str, output_path: str, file_label: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.url = url
        self.output_path = output_path
        self.file_label = file_label

    def run(self):
        try:
            self.titleChanged.emit(self.tr("正在下载附件"))
            self.messageChanged.emit(self.tr("准备下载：{0}").format(self.file_label))
            self.maximumChanged.emit(100)
            self.progressChanged.emit(0)

            response = self.session.get(self.url, stream=True, timeout=60)
            response.raise_for_status()
            total_raw = response.headers.get("Content-Length")
            total = int(total_raw) if total_raw and str(total_raw).isdigit() else None
            downloaded = 0

            if total is None or total <= 0:
                self.progressPaused.emit(True)
            else:
                self.progressPaused.emit(False)

            with open(self.output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.can_run:
                        self.canceled.emit()
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total and total > 0:
                        progress = int(downloaded * 100 / total)
                        self.progressChanged.emit(min(progress, 100))
                        self.messageChanged.emit(
                            self.tr("{0} / {1}").format(
                                LMSInterface.format_size(downloaded),
                                LMSInterface.format_size(total)
                            )
                        )
                    else:
                        self.messageChanged.emit(self.tr("已下载 {0}").format(LMSInterface.format_size(downloaded)))

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("下载完成"))
            self.hasFinished.emit()
        except Exception as e:
            self.error.emit(self.tr("下载失败"), str(e))


class LMSInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._onlyNotice = None
        self.selected_course_id: int | None = None
        self.selected_activity_id: int | None = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._courses: list[dict] = []
        self._activities: list[dict] = []
        self._filtered_activities: list[dict] = []
        self._current_detail_uploads: list[dict] = []
        self._current_submission: dict | None = None
        self._download_jobs: list[tuple[ProgressInfoBar, LMSFileDownloadThread]] = []
        self.activity_type_filter = "homework"

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
        self.vBoxLayout.addSpacing(10)

        self.pageHost = QWidget(self.view)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.pageLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.pageHost)

        self.thread = LMSThread()
        self.processWidget = ProcessWidget(self.thread, self.view, stoppable=True, hide_on_end=True)
        self.processWidget.setVisible(False)
        self.vBoxLayout.addWidget(self.processWidget)

        self._initCoursePage()
        self._initActivityPage()
        self._initDetailPage()
        self._initSubmissionDetailPage()

        self.thread.error.connect(self.onThreadError)
        self.thread.coursesLoaded.connect(self.onCoursesLoaded)
        self.thread.activitiesLoaded.connect(self.onActivitiesLoaded)
        self.thread.activityDetailLoaded.connect(self.onActivityDetailLoaded)
        self.thread.finished.connect(self.unlock)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        StyleSheet.LMS_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.switchPage(self.coursePage)
        self.refreshCourses()

    def _initCoursePage(self):
        self.coursePage = QFrame(self)
        layout = QVBoxLayout(self.coursePage)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.coursePage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)

        self.refreshCoursesButton = PrimaryPushButton(self.tr("刷新课程"), commandFrame)
        self.refreshCoursesButton.setFixedHeight(40)
        self.openWebButton = PushButton(self.tr("打开思源学堂"), commandFrame)
        self.openWebButton.setFixedHeight(40)
        self.refreshCoursesButton.clicked.connect(self.refreshCourses)
        self.openWebButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://lms.xjtu.edu.cn")))

        commandLayout.addWidget(self.refreshCoursesButton)
        commandLayout.addStretch(1)
        commandLayout.addWidget(self.openWebButton)

        self.userInfoLabel = CaptionLabel(self.tr("当前用户 未加载"), self.coursePage)

        self.courseTable = TableWidget(self.coursePage)
        self.courseTable.setRowCount(0)
        self.courseTable.setColumnCount(6)
        self.courseTable.setHorizontalHeaderLabels([
            self.tr("课程"), self.tr("学年学期"), self.tr("任课教师"), self.tr("学分"), self.tr("发布"), self.tr("教学班")
        ])
        self.apply_default_column_width(self.courseTable)
        self.courseTable.verticalHeader().setVisible(False)
        self.courseTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.courseTable.setMinimumHeight(0)
        self.courseTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.courseTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.courseTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.courseTable.cellClicked.connect(self.onCourseClicked)

        self.courseLoadingFrame = self.create_loading_frame(self.coursePage)
        self.courseLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.userInfoLabel)
        layout.addWidget(self.courseTable)
        layout.addWidget(self.courseLoadingFrame)

        self.pageLayout.addWidget(self.coursePage)

    def _initActivityPage(self):
        self.activityPage = QFrame(self)
        layout = QVBoxLayout(self.activityPage)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.activityPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToCourseButton = PushButton(self.tr("返回课程"), commandFrame)
        self.refreshActivitiesButton = PrimaryPushButton(self.tr("刷新活动"), commandFrame)
        self.backToCourseButton.setFixedHeight(40)
        self.refreshActivitiesButton.setFixedHeight(40)
        self.backToCourseButton.clicked.connect(lambda: self.switchPage(self.coursePage))
        self.refreshActivitiesButton.clicked.connect(self.refreshActivities)
        commandLayout.addWidget(self.backToCourseButton)
        commandLayout.addWidget(self.refreshActivitiesButton)
        commandLayout.addStretch(1)

        self.activityTypePivot = Pivot(self.activityPage)
        self.activityTypePivot.addItem("homework", self.tr("作业"), onClick=lambda: self.onActivityTypeChanged("homework"))
        self.activityTypePivot.addItem("material", self.tr("资料"), onClick=lambda: self.onActivityTypeChanged("material"))
        self.activityTypePivot.addItem("lesson", self.tr("课程回放"), onClick=lambda: self.onActivityTypeChanged("lesson"))
        self.activityTypePivot.addItem("lecture_live", self.tr("直播"), onClick=lambda: self.onActivityTypeChanged("lecture_live"))
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)

        self.activityTable = TableWidget(self.activityPage)
        self.activityTable.setRowCount(0)
        self.activityTable.setColumnCount(5)
        self.activityTable.setHorizontalHeaderLabels([
            self.tr("活动"), self.tr("开始时间"), self.tr("结束时间"), self.tr("发布"), self.tr("状态")
        ])
        self.apply_default_column_width(self.activityTable)
        self.activityTable.verticalHeader().setVisible(False)
        self.activityTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.activityTable.setMinimumHeight(0)
        self.activityTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.activityTable.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self.activityTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.activityTable.cellClicked.connect(self.onActivityClicked)

        self.activityLoadingFrame = self.create_loading_frame(self.activityPage)
        self.activityLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.activityTypePivot)
        layout.addWidget(self.activityTable)
        layout.addWidget(self.activityLoadingFrame)

        self.pageLayout.addWidget(self.activityPage)

    def _initDetailPage(self):
        self.detailPage = QFrame(self)
        layout = QVBoxLayout(self.detailPage)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.detailPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToActivityButton = PushButton(self.tr("返回活动"), commandFrame)
        self.backToActivityButton.setFixedHeight(40)
        self.backToActivityButton.clicked.connect(lambda: self.switchPage(self.activityPage))
        commandLayout.addWidget(self.backToActivityButton)
        commandLayout.addStretch(1)

        self.detailTitleLabel = TitleLabel("-", self.detailPage)
        self.detailTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.detailInfoLabel = self.create_section_title(self.tr("详细信息"), self.detailPage)

        self.detailInfoTable = TableWidget(self.detailPage)
        self.detailInfoTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailInfoTable.setColumnCount(2)
        self.detailInfoTable.horizontalHeader().setVisible(False)
        self.detailInfoTable.verticalHeader().setVisible(False)
        self.apply_default_column_width(self.detailInfoTable)
        self.detailInfoTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailInfoTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailRichTitle = self.create_section_title(self.tr("详细说明"), self.detailPage)
        self.detailRichTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailRichTitle.setVisible(False)
        self.detailRichContent = QLabel(self.detailPage)
        self.detailRichContent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.detailRichContent.setWordWrap(True)
        self.detailRichContent.setOpenExternalLinks(True)
        self.detailRichContent.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.detailRichContent.setVisible(False)

        self.detailUploadsTitle = self.create_section_title(self.tr("活动附件"), self.detailPage)
        self.detailUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailUploadsTitle.setVisible(False)
        self.detailUploadsTable = self.create_upload_table(self.detailPage)

        self.detailSubmissionLabel = self.create_section_title(self.tr("每次提交"), self.detailPage)
        self.detailSubmissionLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailSubmissionTable = TableWidget(self.detailPage)
        self.detailSubmissionTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailSubmissionTable.setColumnCount(4)
        self.detailSubmissionTable.setHorizontalHeaderLabels([
            self.tr("得分"), self.tr("提交时间"), self.tr("更新时间"), self.tr("详情")
        ])
        self.apply_default_column_width(self.detailSubmissionTable)
        self.detailSubmissionTable.verticalHeader().setVisible(False)
        self.detailSubmissionTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailSubmissionTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailReplayLabel = self.create_section_title(self.tr("课程回放视频"), self.detailPage)
        self.detailReplayLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailReplayTable = TableWidget(self.detailPage)
        self.detailReplayTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailReplayTable.setColumnCount(3)
        self.detailReplayTable.setHorizontalHeaderLabels([
            self.tr("视频"), self.tr("文件大小"), self.tr("另存为")
        ])
        self.apply_default_column_width(self.detailReplayTable)
        self.detailReplayTable.verticalHeader().setVisible(False)
        self.detailReplayTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailReplayTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailLoadingFrame = self.create_loading_frame(self.detailPage)
        self.detailLoadingFrame.setVisible(False)

        layout.addWidget(commandFrame)
        layout.addWidget(self.detailTitleLabel)
        layout.addWidget(self.detailInfoLabel)
        layout.addWidget(self.detailInfoTable)
        layout.addWidget(self.detailRichTitle)
        layout.addWidget(self.detailRichContent)
        layout.addWidget(self.detailUploadsTitle)
        layout.addWidget(self.detailUploadsTable)
        layout.addWidget(self.detailSubmissionLabel)
        layout.addWidget(self.detailSubmissionTable)
        layout.addWidget(self.detailReplayLabel)
        layout.addWidget(self.detailReplayTable)
        layout.addWidget(self.detailLoadingFrame)
        self.pageLayout.addWidget(self.detailPage)

    def _initSubmissionDetailPage(self):
        self.submissionPage = QFrame(self)
        layout = QVBoxLayout(self.submissionPage)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        commandFrame = QFrame(self.submissionPage)
        commandFrame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        commandLayout = QHBoxLayout(commandFrame)
        self.backToDetailButton = PushButton(self.tr("返回活动详情"), commandFrame)
        self.backToDetailButton.clicked.connect(lambda: self.switchPage(self.detailPage))
        commandLayout.addWidget(self.backToDetailButton)
        commandLayout.addStretch(1)

        self.submissionTitleLabel = TitleLabel("-", self.submissionPage)
        self.submissionTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.submissionCommentTitle = self.create_section_title(self.tr("作业文字内容"), self.submissionPage)
        self.submissionCommentTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.submissionCommentLabel = QLabel(self.submissionPage)
        self.submissionCommentLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionCommentLabel.setWordWrap(True)
        self.submissionCommentLabel.setOpenExternalLinks(True)
        self.submissionCommentLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionInstructorTitle = self.create_section_title(self.tr("老师批语"), self.submissionPage)
        self.submissionInstructorTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionInstructorLabel = QLabel(self.submissionPage)
        self.submissionInstructorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionInstructorLabel.setWordWrap(True)
        self.submissionInstructorLabel.setOpenExternalLinks(True)
        self.submissionInstructorLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionUploadsTitle = self.create_section_title(self.tr("本次提交附件"), self.submissionPage)
        self.submissionUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionUploadsTable = self.create_upload_table(self.submissionPage)
        self.submissionUploadsTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.submissionCorrectTitle = self.create_section_title(self.tr("批阅附件"), self.submissionPage)
        self.submissionCorrectTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionCorrectTable = self.create_upload_table(self.submissionPage)
        self.submissionCorrectTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout.addWidget(commandFrame)
        layout.addWidget(self.submissionTitleLabel)
        layout.addWidget(self.submissionCommentTitle)
        layout.addWidget(self.submissionCommentLabel)
        layout.addWidget(self.submissionInstructorTitle)
        layout.addWidget(self.submissionInstructorLabel)
        layout.addWidget(self.submissionUploadsTitle)
        layout.addWidget(self.submissionUploadsTable)
        layout.addWidget(self.submissionCorrectTitle)
        layout.addWidget(self.submissionCorrectTable)
        self.pageLayout.addWidget(self.submissionPage)

    def create_loading_frame(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        layout = QVBoxLayout(frame)
        label = BodyLabel(self.tr("加载中..."), frame)
        loading = IndeterminateProgressBar(frame)
        loading.setFixedWidth(280)
        layout.addStretch(1)
        layout.addWidget(label, alignment=Qt.AlignHCenter)
        layout.addWidget(loading, alignment=Qt.AlignHCenter)
        layout.addStretch(1)
        return frame

    def switchPage(self, page: QWidget):
        pages = (self.coursePage, self.activityPage, self.detailPage, self.submissionPage)
        for one in pages:
            one.setVisible(one is page)

        self.pageHost.adjustSize()
        self.view.adjustSize()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().setValue(0)

    def show_loading(self, page: QWidget, show: bool):
        mapping = {
            self.coursePage: (self.courseLoadingFrame, [self.courseTable]),
            self.activityPage: (self.activityLoadingFrame, [self.activityTable]),
            self.detailPage: (self.detailLoadingFrame, [self.detailInfoTable, self.detailRichContent,
                                                        self.detailRichTitle, self.detailUploadsTitle,
                                                        self.detailUploadsTable, self.detailSubmissionLabel,
                                                        self.detailSubmissionTable, self.detailReplayLabel,
                                                        self.detailReplayTable]),
        }
        frame, hides = mapping.get(page, (None, []))
        if frame is None:
            return
        frame.setVisible(show)
        for widget in hides:
            widget.setVisible(not show)

    def create_upload_table(self, parent: QWidget) -> TableWidget:
        table = TableWidget(parent)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([self.tr("名称"), self.tr("大小"), self.tr("另存为")])
        self.apply_default_column_width(table)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        return table

    @staticmethod
    def apply_default_column_width(table: TableWidget):
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

    def create_section_title(self, text: str, parent: QWidget) -> StrongBodyLabel:
        label = StrongBodyLabel(text, parent)
        f = label.font()
        f.setBold(True)
        f.setPointSize(max(f.pointSize(), 12))
        label.setFont(f)
        return label

    @staticmethod
    def update_table_height(table: TableWidget, min_rows: int = 0, min_height: int = 38):
        header_h = table.horizontalHeader().height() if table.horizontalHeader().isVisible() else 0
        if table.rowCount() > 0:
            rows_h = table.verticalHeader().length()
        else:
            rows_h = table.verticalHeader().defaultSectionSize() * min_rows
        frame_h = table.frameWidth() * 2
        scrollbar_h = table.horizontalScrollBar().sizeHint().height() if table.horizontalScrollBar().isVisible() else 0
        table.setFixedHeight(max(header_h + rows_h + frame_h + scrollbar_h + 2, min_height))

    def lock(self):
        self.refreshCoursesButton.setEnabled(False)
        self.refreshActivitiesButton.setEnabled(False)
        self.backToCourseButton.setEnabled(False)
        self.backToActivityButton.setEnabled(False)
        self.backToDetailButton.setEnabled(False)
        self.courseTable.setEnabled(False)
        self.activityTable.setEnabled(False)

    def unlock(self):
        self.refreshCoursesButton.setEnabled(True)
        self.refreshActivitiesButton.setEnabled(True)
        self.backToCourseButton.setEnabled(True)
        self.backToActivityButton.setEnabled(True)
        self.backToDetailButton.setEnabled(True)
        self.courseTable.setEnabled(True)
        self.activityTable.setEnabled(True)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
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
        self.error(title, msg, parent=self)
        self.show_loading(self.coursePage, False)
        self.show_loading(self.activityPage, False)
        self.show_loading(self.detailPage, False)

    @pyqtSlot()
    def refreshCourses(self):
        self.show_loading(self.coursePage, True)
        self.switchPage(self.coursePage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_COURSES
        self.thread.start()

    @pyqtSlot()
    def refreshActivities(self):
        if self.selected_course_id is None:
            self.error(self.tr("未选择课程"), self.tr("请先选择一门课程"), parent=self)
            return
        self.show_loading(self.activityPage, True)
        self.switchPage(self.activityPage)
        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_ACTIVITIES
        self.thread.course_id = self.selected_course_id
        self.thread.start()

    @pyqtSlot(dict, list)
    def onCoursesLoaded(self, user_info: dict, courses: list):
        self.show_loading(self.coursePage, False)
        self._courses = courses
        self._activities = []
        self._filtered_activities = []
        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._current_detail_uploads = []

        user_name = user_info.get("name") or self.tr("未知用户")
        user_no = user_info.get("userNo") or "-"
        self.userInfoLabel.setText(self.tr("当前用户 {0} ({1})").format(user_name, user_no))

        self.courseTable.setRowCount(len(courses))
        for row, course in enumerate(courses):
            semester = course.get("semester", {}) if isinstance(course.get("semester"), dict) else {}
            academic_year = course.get("academic_year", {}) if isinstance(course.get("academic_year"), dict) else {}
            course_attr = course.get("course_attributes", {}) if isinstance(course.get("course_attributes"), dict) else {}
            instructors = course.get("instructors", []) if isinstance(course.get("instructors"), list) else []
            instructor_text = "、".join(str(one.get("name", "")) for one in instructors if isinstance(one, dict) and one.get("name"))
            semester_text = f"{academic_year.get('name') or '-'} {semester.get('name') or semester.get('real_name') or '-'}"

            self.courseTable.setItem(row, 0, QTableWidgetItem(str(course.get("name") or "-")))
            self.courseTable.setItem(row, 1, QTableWidgetItem(semester_text.strip()))
            self.courseTable.setItem(row, 2, QTableWidgetItem(instructor_text or "-"))
            self.courseTable.setItem(row, 3, QTableWidgetItem(str(course.get("credit") or "-")))
            self.courseTable.setItem(row, 4, QTableWidgetItem(self.bool_text(course_attr.get("published"))))
            self.courseTable.setItem(row, 5, QTableWidgetItem(str(course_attr.get("teaching_class_name") or "-")))

        self.courseTable.resizeRowsToContents()
        self.update_table_height(self.courseTable, min_rows=1, min_height=140)

        if courses:
            self.success(self.tr("加载完成"), self.tr("已获取 {0} 门课程").format(len(courses)), parent=self)
        else:
            self.success(self.tr("暂无课程"), self.tr("当前账号未获取到课程"), parent=self)

    @pyqtSlot(int, int)
    def onCourseClicked(self, row: int, _column: int):
        if row < 0 or row >= len(self._courses):
            return
        course = self._courses[row]
        course_id = course.get("id")
        if not isinstance(course_id, int):
            return

        self.selected_course_id = course_id
        self.selected_course_name = str(course.get("name") or "-")
        self.activity_type_filter = "homework"
        self.activityTypePivot.setCurrentItem(self.activity_type_filter)
        self.activityTable.setRowCount(0)
        self.refreshActivities()

    @pyqtSlot(int, list)
    def onActivitiesLoaded(self, course_id: int, activities: list):
        self.show_loading(self.activityPage, False)
        if self.selected_course_id != course_id:
            return
        self._activities = activities
        self.filter_activities(self.activity_type_filter)
        self.switchPage(self.activityPage)
        if not activities:
            self.success(self.tr("无活动"), self.tr("该课程暂无可显示活动"), parent=self)

    def onActivityTypeChanged(self, key: str):
        self.activity_type_filter = key
        self.filter_activities(key)

    def filter_activities(self, key: str):
        self._filtered_activities = [one for one in self._activities if str(one.get("type") or "") == key]

        self.activityTable.setRowCount(len(self._filtered_activities))
        for row, activity in enumerate(self._filtered_activities):
            self.activityTable.setItem(row, 0, QTableWidgetItem(str(activity.get("title") or "-")))
            self.activityTable.setItem(row, 1, QTableWidgetItem(self.time_text(activity.get("start_time"))))
            self.activityTable.setItem(row, 2, QTableWidgetItem(self.time_text(activity.get("end_time"))))
            self.activityTable.setItem(row, 3, QTableWidgetItem(self.bool_text(activity.get("published"))))
            self.activityTable.setItem(row, 4, QTableWidgetItem(self.activity_status_text(activity)))

        self.activityTable.resizeRowsToContents()
        self.update_table_height(self.activityTable, min_rows=1, min_height=140)

    @pyqtSlot(int, int)
    def onActivityClicked(self, row: int, _column: int):
        if row < 0 or row >= len(self._filtered_activities):
            return
        activity = self._filtered_activities[row]
        activity_id = activity.get("id")
        if not isinstance(activity_id, int):
            return

        self.selected_activity_id = activity_id
        self.selected_activity_name = str(activity.get("title") or "-")
        self.detailTitleLabel.setText(f"{self.selected_course_name} / {self.selected_activity_name}")
        self.show_loading(self.detailPage, True)
        self.switchPage(self.detailPage)

        self.processWidget.setVisible(True)
        self.lock()
        self.thread.action = LMSAction.LOAD_ACTIVITY_DETAIL
        self.thread.activity_id = activity_id
        self.thread.start()

    @pyqtSlot(int, dict)
    def onActivityDetailLoaded(self, activity_id: int, detail: dict):
        self.show_loading(self.detailPage, False)
        if self.selected_activity_id != activity_id:
            return

        uploads = detail.get("uploads", []) if isinstance(detail.get("uploads"), list) else []
        self._current_detail_uploads = [one for one in uploads if isinstance(one, dict)]
        self.populate_upload_table(self.detailUploadsTable, self._current_detail_uploads)
        self.detailUploadsTitle.setVisible(self.detailUploadsTable.isVisible())

        info_rows, rich_text = self.build_detail_rows(detail)
        self.populate_info_table(self.detailInfoTable, info_rows)
        self.set_html_label(self.detailRichContent, rich_text)
        has_rich = bool(rich_text and str(rich_text).strip() and str(rich_text).strip() != "-")
        self.detailRichContent.setVisible(has_rich)
        self.detailRichTitle.setVisible(has_rich)

        submission_rows = []
        submission_list = detail.get("submission_list", {})
        if isinstance(submission_list, dict):
            submission_rows = submission_list.get("list", []) if isinstance(submission_list.get("list"), list) else []
        self._set_submission_rows(submission_rows)

        replay_rows = detail.get("replay_videos", []) if isinstance(detail.get("replay_videos"), list) else []
        if str(detail.get("type") or "") == "lesson":
            replay_rows = [one for one in replay_rows if isinstance(one, dict) and str(one.get("label") or "") in {"ENCODER", "INSTRUCTOR"}]
        else:
            replay_rows = []
        self._set_replay_rows(replay_rows)

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        self.courseTable.setRowCount(0)
        self.activityTable.setRowCount(0)
        self.update_table_height(self.courseTable, min_rows=1, min_height=140)
        self.update_table_height(self.activityTable, min_rows=1, min_height=140)
        self.populate_info_table(self.detailInfoTable, [(self.tr("提示"), self.tr("请选择一个活动查看详情"))])
        self.detailRichContent.setVisible(False)
        self.detailRichTitle.setVisible(False)
        self.detailUploadsTitle.setVisible(False)
        self.populate_upload_table(self.detailUploadsTable, [])
        self._set_submission_rows([])
        self._set_replay_rows([])

        self.selected_course_id = None
        self.selected_activity_id = None
        self.selected_course_name = ""
        self.selected_activity_name = ""
        self._courses = []
        self._activities = []
        self._filtered_activities = []
        self._current_detail_uploads = []
        self._current_submission = None

        self.switchPage(self.coursePage)

    def _set_submission_rows(self, submissions):
        rows = [one for one in submissions if isinstance(one, dict)] if isinstance(submissions, list) else []
        self.detailSubmissionTable.setRowCount(len(rows))
        for row, sub in enumerate(rows):
            self.detailSubmissionTable.setItem(row, 0, QTableWidgetItem(self.safe_text(sub.get("score"))))
            self.detailSubmissionTable.setItem(row, 1, QTableWidgetItem(self.time_text(sub.get("submitted_at"))))
            self.detailSubmissionTable.setItem(row, 2, QTableWidgetItem(self.time_text(sub.get("updated_at"))))

            detail_btn = PushButton(self.tr("查看详情"), self.detailSubmissionTable)
            detail_btn.clicked.connect(lambda _=False, one=sub: self.show_submission_page(one))
            self.detailSubmissionTable.setCellWidget(row, 3, detail_btn)

        visible = len(rows) > 0
        self.detailSubmissionLabel.setVisible(visible)
        self.detailSubmissionTable.setVisible(visible)
        self.detailSubmissionTable.resizeRowsToContents()
        self.update_table_height(self.detailSubmissionTable, min_rows=0, min_height=38)

    def _set_replay_rows(self, replay_videos):
        rows = [one for one in replay_videos if isinstance(one, dict)] if isinstance(replay_videos, list) else []
        self.detailReplayTable.setRowCount(len(rows))
        for row, video in enumerate(rows):
            self.detailReplayTable.setItem(row, 0, QTableWidgetItem(self.safe_text(video.get("label"))))
            self.detailReplayTable.setItem(row, 1, QTableWidgetItem(self.format_size(video.get("size"))))

            save_btn = PushButton(self.tr("另存为"), self.detailReplayTable)
            save_btn.clicked.connect(lambda _=False, one=video: self._save_file(one))
            self.detailReplayTable.setCellWidget(row, 2, save_btn)

        visible = len(rows) > 0
        self.detailReplayLabel.setVisible(visible)
        self.detailReplayTable.setVisible(visible)
        self.detailReplayTable.resizeRowsToContents()
        self.update_table_height(self.detailReplayTable, min_rows=0, min_height=38)

    def show_submission_page(self, submission: dict):
        self._current_submission = submission
        self.submissionTitleLabel.setText(f"{self.selected_course_name} / {self.selected_activity_name}")

        has_comment = self.set_html_label(self.submissionCommentLabel, submission.get("comment"))
        self.submissionCommentTitle.setVisible(has_comment)
        self.submissionCommentLabel.setVisible(has_comment)

        has_instructor = self.set_html_label(self.submissionInstructorLabel, submission.get("instructor_comment"))
        self.submissionInstructorTitle.setVisible(has_instructor)
        self.submissionInstructorLabel.setVisible(has_instructor)

        sub_uploads = submission.get("uploads", []) if isinstance(submission.get("uploads"), list) else []
        sub_upload_count = self.populate_upload_table(self.submissionUploadsTable, sub_uploads)
        self.submissionUploadsTitle.setVisible(sub_upload_count > 0)
        self.submissionUploadsTable.setVisible(sub_upload_count > 0)

        submission_correct = submission.get("submission_correct", {}) if isinstance(submission.get("submission_correct"), dict) else {}
        correct_uploads = submission_correct.get("uploads", []) if isinstance(submission_correct.get("uploads"), list) else []
        correct_upload_count = self.populate_upload_table(self.submissionCorrectTable, correct_uploads)
        self.submissionCorrectTitle.setVisible(correct_upload_count > 0)
        self.submissionCorrectTable.setVisible(correct_upload_count > 0)

        self.switchPage(self.submissionPage)
        QTimer.singleShot(0, self._refresh_submission_upload_table_heights)

    def _refresh_submission_upload_table_heights(self):
        for table in (self.submissionUploadsTable, self.submissionCorrectTable):
            if table.isVisible():
                table.resizeRowsToContents()
                self.update_table_height(table, min_rows=0, min_height=38)

    def _open_file(self, file_info: dict):
        url = file_info.get("preview_url") or file_info.get("download_url")
        if not isinstance(url, str) or not url:
            self.error(self.tr("无法查看"), self.tr("该文件没有可用链接"), parent=self)
            return
        QDesktopServices.openUrl(QUrl(url))

    def _save_file(self, file_info: dict):
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
            session = accounts.current.session_manager.get_session("lms")
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
        self._download_jobs = [one for one in self._download_jobs if one != (bar, thread)]

    def populate_upload_table(self, table: TableWidget, uploads) -> int:
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        table.setRowCount(len(rows))
        for row, upload in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(self.safe_text(upload.get("name"))))
            table.setItem(row, 1, QTableWidgetItem(self.format_size(upload.get("size"))))

            save_btn = PushButton(self.tr("另存为"), table)
            save_btn.clicked.connect(lambda _=False, one=upload: self._save_file(one))
            table.setCellWidget(row, 2, save_btn)

        if table is self.detailUploadsTable:
            visible = len(rows) > 0
            self.detailUploadsTable.setVisible(visible)

        table.resizeRowsToContents()
        self.update_table_height(table, min_rows=0, min_height=38)
        return len(rows)

    def populate_info_table(self, table: TableWidget, rows: list[tuple[str, object]]):
        table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        table.setWordWrap(True)

        for row, (header, value) in enumerate(rows):
            header_item = QTableWidgetItem(str(header))
            header_item.setFont(bold)
            table.setItem(row, 0, header_item)

            item = QTableWidgetItem(self.safe_text(value))
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            table.setItem(row, 1, item)

        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        self.update_table_height(table, min_rows=1, min_height=38)

    def build_detail_rows(self, detail: dict) -> tuple[list[tuple[str, object]], str | None]:
        type_name = str(detail.get("type") or "")
        if type_name == "lesson":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("课程开始时间"), self.time_text(detail.get("lesson_start"))),
                (self.tr("课程结束时间"), self.time_text(detail.get("lesson_end"))),
            ], None

        if type_name == "homework":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
                (self.tr("提交方式"), self.tr("小组") if detail.get("submit_by_group") else self.tr("个人")),
                (self.tr("最高分"), detail.get("highest_score")),
                (self.tr("最低分"), detail.get("lowest_score")),
                (self.tr("平均分"), detail.get("average_score")),
            ], self.safe_text(detail.get("description"))

        if type_name == "material":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
            ], self.safe_text(detail.get("description"))

        if type_name == "lecture_live":
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
                (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
                (self.tr("直播间"), self.format_live_room(detail.get("live_room"))),
            ], None

        return [
            (self.tr("标题"), detail.get("title")),
            (self.tr("类型"), self.activity_type_text(detail.get("type"))),
            (self.tr("开始时间"), self.time_text(detail.get("start_time"))),
            (self.tr("结束时间"), self.time_text(detail.get("end_time"))),
        ], None

    def set_html_label(self, label: QLabel, value):
        text = self.safe_text(value)
        if text == "-":
            label.clear()
            label.setStyleSheet("")
            return False

        if self.is_html_text(text):
            link_color = "#0066CC"
            html = (
                "<style>"
                "body{font-size:17px;}"
                "body{background:#FFFFFF;color:#000000;}"
                "div{background:#FFFFFF;color:#000000;padding:8px;border-radius:4px;}"
                f"a{{color:{link_color};}}"
                "p{margin:0;} div{margin:0;}"
                "</style>"
                f"<div>{text}</div>"
            )
            label.setTextFormat(Qt.RichText)
            label.setText(html)
            label.setStyleSheet("QLabel { background-color: #FFFFFF; color: #000000; padding: 6px; border-radius: 4px; }")
            return True
        else:
            label.setTextFormat(Qt.PlainText)
            label.setText(text)
            label.setStyleSheet("QLabel { background-color: #FFFFFF; color: #000000; padding: 6px; border-radius: 4px; }")
            return True

    @staticmethod
    def time_text(value):
        if isinstance(value, str) and value:
            return value.replace("T", " ")
        return "-"

    @staticmethod
    def bool_text(value):
        if value is True:
            return "是"
        if value is False:
            return "否"
        return "-"

    @staticmethod
    def safe_text(value):
        if value is None or value == "":
            return "-"
        return str(value)

    @staticmethod
    def activity_type_text(value):
        mapping = {
            "homework": "作业",
            "material": "资料",
            "lesson": "课程回放",
            "lecture_live": "直播",
        }
        return mapping.get(str(value), str(value) if value else "-")

    @staticmethod
    def activity_status_text(activity: dict):
        if activity.get("is_closed") is True:
            return "已结束"
        if activity.get("is_in_progress") is True:
            return "进行中"
        if activity.get("is_started") is True:
            return "已开始"
        return "未开始"

    @staticmethod
    def format_live_room(value) -> str:
        if isinstance(value, dict):
            room_name = value.get("room_name")
            building = value.get("name")
            code = value.get("room_code")
            parts = []
            if building:
                parts.append(str(building))
            if room_name:
                parts.append(str(room_name))
            if code:
                parts.append(f"({code})")
            return " ".join(parts) if parts else "-"
        return LMSInterface.safe_text(value)

    @staticmethod
    def is_html_text(text: str) -> bool:
        if not isinstance(text, str):
            return False
        if "<" not in text or ">" not in text:
            return False
        return bool(re.search(r"<\s*/?\s*\w+[^>]*>", text))

    @staticmethod
    def format_size(size) -> str:
        if not isinstance(size, (int, float)) or size < 0:
            return "-"
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}"
            value /= 1024
        return "-"

    @staticmethod
    def sanitize_filename(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "attachment"

    def build_default_filename(self, file_info: dict) -> str:
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
