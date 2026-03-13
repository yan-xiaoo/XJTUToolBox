from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy, QTableWidgetItem
from qfluentwidgets import PushButton, TableWidget, TitleLabel

from lms.models import ActivityType
from .common import (
    PageStatus,
    create_loading_frame,
    create_retry_frame,
    create_section_title,
    apply_default_column_width,
    update_table_height,
    safe_text,
    time_text,
    format_live_room,
    activity_type_text,
    set_html_label,
    populate_info_table,
    format_size,
)


class LMSDetailPage(QFrame):
    # 用户点击重试后，请求主容器重新加载活动详情。
    retryRequested = pyqtSignal()
    # 用户点击“查看详情”后，通知主容器打开提交详情页。
    submissionRequested = pyqtSignal(dict)
    # 用户点击下载按钮后，通知主容器执行下载。
    downloadRequested = pyqtSignal(dict)

    def __init__(self, parent=None):
        """初始化活动详情页组件。"""
        super().__init__(parent)
        self.setObjectName("detailPage")

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        self.detailTitleLabel = TitleLabel("-", self)
        self.detailTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.detailInfoLabel = create_section_title(self, self.tr("详细信息"))
        self.detailInfoTable = TableWidget(self)
        self.detailInfoTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailInfoTable.setColumnCount(2)
        self.detailInfoTable.horizontalHeader().setVisible(False)
        self.detailInfoTable.verticalHeader().setVisible(False)
        apply_default_column_width(self.detailInfoTable)
        self.detailInfoTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailInfoTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailRichTitle = create_section_title(self, self.tr("详细说明"))
        self.detailRichTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailRichTitle.setVisible(False)
        self.detailRichContent = QLabel(self)
        self.detailRichContent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.detailRichContent.setWordWrap(True)
        self.detailRichContent.setOpenExternalLinks(True)
        self.detailRichContent.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.detailRichContent.setVisible(False)

        self.detailUploadsTitle = create_section_title(self, self.tr("活动附件"))
        self.detailUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailUploadsTitle.setVisible(False)
        self.detailUploadsTable = self._createUploadTable()

        self.detailSubmissionLabel = create_section_title(self, self.tr("每次提交"))
        self.detailSubmissionLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailSubmissionTable = TableWidget(self)
        self.detailSubmissionTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailSubmissionTable.setColumnCount(4)
        self.detailSubmissionTable.setHorizontalHeaderLabels([
            self.tr("得分"), self.tr("提交时间"), self.tr("更新时间"), self.tr("详情")
        ])
        apply_default_column_width(self.detailSubmissionTable)
        self.detailSubmissionTable.verticalHeader().setVisible(False)
        self.detailSubmissionTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailSubmissionTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailReplayLabel = create_section_title(self, self.tr("课程回放视频"))
        self.detailReplayLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailReplayTable = TableWidget(self)
        self.detailReplayTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailReplayTable.setColumnCount(3)
        self.detailReplayTable.setHorizontalHeaderLabels([
            self.tr("视频"), self.tr("文件大小"), self.tr("另存为")
        ])
        apply_default_column_width(self.detailReplayTable)
        self.detailReplayTable.verticalHeader().setVisible(False)
        self.detailReplayTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailReplayTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.loadingFrame = create_loading_frame(self)
        self.loadingFrame.setVisible(False)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

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
        layout.addWidget(self.loadingFrame)
        layout.addWidget(self.failFrame)

    def _createUploadTable(self) -> TableWidget:
        """创建附件表格。"""
        table = TableWidget(self)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([self.tr("名称"), self.tr("大小"), self.tr("另存为")])
        apply_default_column_width(table)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        return table

    def setPageStatus(self, status: PageStatus):
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL/LOADING/ERROR。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            self.loadingFrame.setVisible(True)
            for one in self._normalWidgets():
                one.setVisible(False)
            self.failFrame.setVisible(False)
            return
        if status == PageStatus.ERROR:
            self.loadingFrame.setVisible(False)
            for one in self._normalWidgets():
                one.setVisible(False)
            self.failFrame.setVisible(True)
            return

        self.loadingFrame.setVisible(False)
        for one in self._normalWidgets():
            one.setVisible(True)
        self.failFrame.setVisible(False)

    def _normalWidgets(self):
        """返回详情页常规显示控件集合。"""
        return [
            self.detailInfoTable, self.detailRichContent,
            self.detailRichTitle, self.detailUploadsTitle,
            self.detailUploadsTable, self.detailSubmissionLabel,
            self.detailSubmissionTable, self.detailReplayLabel,
            self.detailReplayTable,
        ]

    def setDetail(self, detail: dict, course_name: str, activity_name: str):
        """填充活动详情页数据。

        :param detail: 活动详情字典。
        :param course_name: 当前课程名称，用于标题展示。
        :param activity_name: 当前活动名称，用于标题展示。
        :return: 无返回值。
        """
        self.detailTitleLabel.setText(f"{course_name} / {activity_name}")

        uploads = detail.get("uploads", []) if isinstance(detail.get("uploads"), list) else []
        upload_count = self._populateUploadTable(self.detailUploadsTable, uploads)
        self.detailUploadsTitle.setVisible(upload_count > 0)
        self.detailUploadsTable.setVisible(upload_count > 0)

        info_rows, rich_text = self._buildDetailRows(detail)
        populate_info_table(self.detailInfoTable, info_rows)

        has_rich = set_html_label(self.detailRichContent, rich_text)
        self.detailRichContent.setVisible(has_rich)
        self.detailRichTitle.setVisible(has_rich)

        submission_rows = []
        submission_list = detail.get("submission_list", {})
        if isinstance(submission_list, dict):
            submission_rows = submission_list.get("list", []) if isinstance(submission_list.get("list"), list) else []
        self._setSubmissionRows(submission_rows)

        replay_rows = detail.get("replay_videos", []) if isinstance(detail.get("replay_videos"), list) else []
        if str(detail.get("type") or "") == ActivityType.LESSON.value:
            replay_rows = [one for one in replay_rows if isinstance(one, dict) and str(one.get("label") or "") in {"ENCODER", "INSTRUCTOR"}]
        else:
            replay_rows = []
        self._setReplayRows(replay_rows)

    def reset(self):
        """重置详情页到默认提示状态。

        :return: 无返回值。
        """
        self.detailTitleLabel.setText("-")
        populate_info_table(self.detailInfoTable, [(self.tr("提示"), self.tr("请选择一个活动查看详情"))])
        self.detailRichContent.setVisible(False)
        self.detailRichTitle.setVisible(False)
        self.detailUploadsTitle.setVisible(False)
        self._populateUploadTable(self.detailUploadsTable, [])
        self._setSubmissionRows([])
        self._setReplayRows([])
        self.setPageStatus(PageStatus.NORMAL)

    def _setSubmissionRows(self, submissions):
        """渲染“每次提交”区域。"""
        rows = [one for one in submissions if isinstance(one, dict)] if isinstance(submissions, list) else []
        self.detailSubmissionTable.setRowCount(len(rows))
        for row, sub in enumerate(rows):
            self.detailSubmissionTable.setItem(row, 0, QTableWidgetItem(safe_text(sub.get("score"))))
            self.detailSubmissionTable.setItem(row, 1, QTableWidgetItem(time_text(sub.get("submitted_at"))))
            self.detailSubmissionTable.setItem(row, 2, QTableWidgetItem(time_text(sub.get("updated_at"))))

            detail_btn = PushButton(self.tr("查看详情"), self.detailSubmissionTable)
            detail_btn.clicked.connect(lambda _=False, one=sub: self.submissionRequested.emit(one))
            self.detailSubmissionTable.setCellWidget(row, 3, detail_btn)

        visible = len(rows) > 0
        self.detailSubmissionLabel.setVisible(visible)
        self.detailSubmissionTable.setVisible(visible)
        self.detailSubmissionTable.resizeRowsToContents()
        update_table_height(self.detailSubmissionTable, min_rows=0, min_height=38)

    def _setReplayRows(self, replay_videos):
        """渲染“课程回放视频”区域。"""
        rows = [one for one in replay_videos if isinstance(one, dict)] if isinstance(replay_videos, list) else []
        self.detailReplayTable.setRowCount(len(rows))
        for row, video in enumerate(rows):
            self.detailReplayTable.setItem(row, 0, QTableWidgetItem(safe_text(video.get("label"))))
            self.detailReplayTable.setItem(row, 1, QTableWidgetItem(format_size(video.get("size"))))

            save_btn = PushButton(self.tr("另存为"), self.detailReplayTable)
            save_btn.clicked.connect(lambda _=False, one=video: self.downloadRequested.emit(one))
            self.detailReplayTable.setCellWidget(row, 2, save_btn)

        visible = len(rows) > 0
        self.detailReplayLabel.setVisible(visible)
        self.detailReplayTable.setVisible(visible)
        self.detailReplayTable.resizeRowsToContents()
        update_table_height(self.detailReplayTable, min_rows=0, min_height=38)

    def _populateUploadTable(self, table: TableWidget, uploads) -> int:
        """渲染附件表格并返回附件数量。"""
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        table.setRowCount(len(rows))
        for row, upload in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(safe_text(upload.get("name"))))
            table.setItem(row, 1, QTableWidgetItem(format_size(upload.get("size"))))

            save_btn = PushButton(self.tr("另存为"), table)
            save_btn.clicked.connect(lambda _=False, one=upload: self.downloadRequested.emit(one))
            table.setCellWidget(row, 2, save_btn)

        table.resizeRowsToContents()
        update_table_height(table, min_rows=0, min_height=38)
        return len(rows)

    def _buildDetailRows(self, detail: dict) -> tuple[list[tuple[str, object]], str | None]:
        """根据活动类型构建信息区字段与富文本说明。"""
        type_name = str(detail.get("type") or "")
        if type_name == ActivityType.LESSON.value:
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("课程开始时间"), time_text(detail.get("lesson_start"))),
                (self.tr("课程结束时间"), time_text(detail.get("lesson_end"))),
            ], None

        if type_name == ActivityType.HOMEWORK.value:
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), time_text(detail.get("start_time"))),
                (self.tr("结束时间"), time_text(detail.get("end_time"))),
                (self.tr("提交方式"), self.tr("小组") if detail.get("submit_by_group") else self.tr("个人")),
                (self.tr("最高分"), detail.get("highest_score")),
                (self.tr("最低分"), detail.get("lowest_score")),
                (self.tr("平均分"), detail.get("average_score")),
            ], safe_text(detail.get("description"))

        if type_name == ActivityType.MATERIAL.value:
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), time_text(detail.get("start_time"))),
                (self.tr("结束时间"), time_text(detail.get("end_time"))),
            ], safe_text(detail.get("description"))

        if type_name == ActivityType.LECTURE_LIVE.value:
            return [
                (self.tr("标题"), detail.get("title")),
                (self.tr("开始时间"), time_text(detail.get("start_time"))),
                (self.tr("结束时间"), time_text(detail.get("end_time"))),
                (self.tr("直播间"), format_live_room(detail.get("live_room"))),
            ], None

        return [
            (self.tr("标题"), detail.get("title")),
            (self.tr("类型"), activity_type_text(detail.get("type"))),
            (self.tr("开始时间"), time_text(detail.get("start_time"))),
            (self.tr("结束时间"), time_text(detail.get("end_time"))),
        ], None
