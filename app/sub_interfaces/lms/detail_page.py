from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FlowLayout,
    FluentIcon,
    HeaderCardWidget,
    IconWidget,
    PushButton,
    SimpleCardWidget,
    TableWidget,
    TextBrowser,
    TitleLabel, PrimaryPushButton,
)

from lms.models import ActivityType
from .common import (
    ATTACHMENT_ACTION_BUTTON_WIDTH,
    ATTACHMENT_ACTION_COLUMN_WIDTH,
    PageStatus,
    activity_type_text,
    can_preview_as_image,
    create_loading_frame,
    create_retry_frame,
    create_section_title,
    format_live_room,
    format_replay_video_label,
    format_size,
    safe_text,
    set_html_label,
    time_text,
    update_table_height, apply_stretch_and_fixed_column_width,
    apply_stretch_on_first_column,
)

MetaItem = tuple[FluentIcon, str, str]


class DetailDescriptionBrowser(TextBrowser):
    """自适应高度的活动说明浏览器。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化说明浏览器。

        :param parent: 父级控件，用于挂载浏览器。
        :return: 无返回值。
        """
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().setDocumentMargin(0)

    def setDocumentContent(self, content: str, is_html: bool) -> None:
        """写入说明内容并刷新控件高度。

        :param content: 待展示的说明文本或 HTML。
        :param is_html: 为 True 时按 HTML 渲染，否则按纯文本渲染。
        :return: 无返回值。
        """
        if is_html:
            self.setHtml(content)
        else:
            self.setPlainText(content)
        self._refreshHeight()

    def resizeEvent(self, event) -> None:
        """在控件宽度变化时重新计算浏览器高度。"""
        super().resizeEvent(event)
        self._refreshHeight()

    def _refreshHeight(self) -> None:
        """根据文档内容刷新说明浏览器高度。"""
        viewport_width = self.viewport().width()
        if viewport_width > 0:
            self.document().setTextWidth(float(viewport_width))

        document_height = self.document().size().height()
        frame_height = self.frameWidth() * 2
        margin_height = self.contentsMargins().top() + self.contentsMargins().bottom()
        self.setFixedHeight(max(int(document_height + frame_height + margin_height + 8), 20))


class DetailMetaCard(SimpleCardWidget):
    """详情页标题下方的图标信息卡片。"""

    def __init__(self, icon: FluentIcon, title: str, value: str, parent: Optional[QWidget] = None) -> None:
        """初始化单个信息卡片。

        :param icon: 信息项左侧展示的 Fluent 图标。
        :param title: 信息项标题，如“截止”“平均分”。
        :param value: 信息项正文内容。
        :param parent: 父级控件，用于挂载卡片。
        :return: 无返回值。
        """
        super().__init__(parent)
        self.setObjectName("detailMetaCard")
        self.setMinimumWidth(220)
        self.setMaximumWidth(360)
        self.setFixedHeight(60)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(18, 18)

        self.titleLabel = CaptionLabel(title, self)
        self.titleLabel.setTextColor("#606060", "#d2d2d2")

        self.valueLabel = BodyLabel(value, self)
        self.valueLabel.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.titleLabel)
        text_layout.addWidget(self.valueLabel)

        layout.addWidget(self.iconWidget, 0, Qt.AlignVCenter)
        layout.addLayout(text_layout, stretch=1)


class LMSDetailPage(QFrame):
    # 用户点击重试后，请求主容器重新加载活动详情。
    retryRequested = pyqtSignal()
    # 用户点击“查看详情”后，通知主容器打开提交详情页。
    submissionRequested = pyqtSignal(dict)
    # 用户点击下载按钮后，通知主容器执行下载。
    downloadRequested = pyqtSignal(dict)
    # 用户点击图片预览后，通知主容器打开预览对话框。
    previewRequested = pyqtSignal(dict, list)
    # 用户点击“在线查看”后，请求主容器切换到视频播放页。
    replayVideoViewRequested = pyqtSignal(dict)
    # 用户点击“打开对应回放”后，请求主容器按开始时间跳转到对应 lesson。
    relatedLessonRequested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化活动详情页组件。

        :param parent: 父级控件，通常为 LMS 主容器。
        :return: 无返回值。
        """
        super().__init__(parent)
        self.setObjectName("detailPage")
        self._metaCards: list[QWidget] = []
        self._relatedLessonStartTime: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 8, 12, 20)
        layout.setAlignment(Qt.AlignTop)

        self.detailTitleLabel = TitleLabel("-", self)
        self.detailTitleLabel.setWordWrap(True)
        self.detailTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.detailMetaHost = QWidget(self)
        self.detailMetaLayout = FlowLayout(self.detailMetaHost, needAni=False)
        self.detailMetaLayout.setContentsMargins(0, 0, 0, 0)
        self.detailMetaLayout.setHorizontalSpacing(12)
        self.detailMetaLayout.setVerticalSpacing(12)

        self.openRelatedLessonButton = PrimaryPushButton(self.tr("打开对应回放"), self)
        self.openRelatedLessonButton.setVisible(False)
        self.openRelatedLessonButton.clicked.connect(self._onOpenRelatedLessonClicked)

        self.detailDescriptionCard = HeaderCardWidget(self.tr("活动说明"), self)
        self.detailDescriptionCard.viewLayout.setContentsMargins(20, 15, 20, 15)
        self.detailDescriptionCard.viewLayout.setSpacing(0)

        self.detailDescriptionLabel = QLabel(self.detailDescriptionCard)
        self.detailDescriptionLabel.setWordWrap(True)
        self.detailDescriptionLabel.setOpenExternalLinks(True)
        self.detailDescriptionLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.detailDescriptionLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.detailDescriptionCard.viewLayout.addWidget(self.detailDescriptionLabel)

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
        apply_stretch_and_fixed_column_width(self.detailSubmissionTable)
        self.detailSubmissionTable.verticalHeader().setVisible(False)
        self.detailSubmissionTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailSubmissionTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailReplayLabel = create_section_title(self, self.tr("课程回放视频"))
        self.detailReplayLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.detailReplayTable = TableWidget(self)
        self.detailReplayTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.detailReplayTable.setColumnCount(4)
        self.detailReplayTable.setHorizontalHeaderLabels([
            self.tr("视频"), self.tr("文件大小"), self.tr("在线播放"), self.tr("另存为")
        ])
        apply_stretch_on_first_column(self.detailReplayTable)
        self.detailReplayTable.verticalHeader().setVisible(False)
        self.detailReplayTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.detailReplayTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.detailReplayWarning = CaptionLabel(self.tr("警告：在线播放视频会消耗大量流量，请确保你连接了 WLAN 网络。"), self)

        self.loadingFrame = create_loading_frame(self)
        self.loadingFrame.setVisible(False)

        self.failFrame, retry_button = create_retry_frame(self)
        self.failFrame.setVisible(False)
        retry_button.clicked.connect(self.retryRequested.emit)

        layout.addWidget(self.detailTitleLabel)
        layout.addWidget(self.detailMetaHost)
        layout.addWidget(self.openRelatedLessonButton, alignment=Qt.AlignLeft)
        layout.addWidget(self.detailDescriptionCard)
        layout.addSpacing(4)
        layout.addWidget(self.detailUploadsTitle)
        layout.addWidget(self.detailUploadsTable)
        layout.addWidget(self.detailSubmissionLabel)
        layout.addWidget(self.detailSubmissionTable)
        layout.addWidget(self.detailReplayLabel)
        layout.addWidget(self.detailReplayTable)
        layout.addSpacing(4)
        layout.addWidget(self.detailReplayWarning)
        layout.addWidget(self.loadingFrame)
        layout.addWidget(self.failFrame)

    def _createUploadTable(self) -> TableWidget:
        """创建附件表格。"""
        table = TableWidget(self)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([self.tr("名称"), self.tr("大小"), self.tr("另存为")])
        apply_stretch_on_first_column(table)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        return table

    def setPageStatus(self, status: PageStatus) -> None:
        """设置页面状态并切换显示区域。

        :param status: 页面状态，支持 NORMAL、LOADING、ERROR 三种取值。
        :return: 无返回值。
        """
        if status == PageStatus.LOADING:
            self.detailTitleLabel.clear()
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
        self.detailMetaHost.setVisible(bool(self._metaCards))
        self.openRelatedLessonButton.setVisible(self._relatedLessonStartTime is not None)
        self.detailDescriptionCard.setVisible(bool(self.detailDescriptionLabel.text().strip()))
        self.failFrame.setVisible(False)

    def _normalWidgets(self) -> list[QWidget]:
        """返回详情页常规显示控件集合。"""
        return [
            self.detailMetaHost,
            self.openRelatedLessonButton,
            self.detailDescriptionCard,
            self.detailUploadsTitle,
            self.detailUploadsTable,
            self.detailSubmissionLabel,
            self.detailSubmissionTable,
            self.detailReplayLabel,
            self.detailReplayTable,
            self.detailReplayWarning
        ]

    def setDetail(self, detail: dict, course_name: str, activity_name: str) -> None:
        """填充活动详情页数据。

        :param detail: 活动详情字典，包含附件、描述、提交记录、回放视频等信息。
        :param course_name: 当前课程名称，当前实现中仅用于保持与主容器接口兼容。
        :param activity_name: 当前活动名称，用于标题展示。
        :return: 无返回值。
        """
        _ = course_name
        self.detailTitleLabel.setText(activity_name)

        self._setMetaItems(self._buildDetailMetaItems(detail))
        self._setRelatedLessonButton(detail)
        self._setDescriptionContent(self._extractRichText(detail))

        uploads = detail.get("uploads", []) if isinstance(detail.get("uploads"), list) else []
        upload_count = self._populateUploadTable(self.detailUploadsTable, uploads)
        self.detailUploadsTitle.setVisible(upload_count > 0)
        self.detailUploadsTable.setVisible(upload_count > 0)

        submission_rows: list[dict] = []
        submission_list = detail.get("submission_list", {})
        if isinstance(submission_list, dict):
            maybe_rows = submission_list.get("list")
            if isinstance(maybe_rows, list):
                submission_rows = [one for one in maybe_rows if isinstance(one, dict)]
        self._setSubmissionRows(submission_rows)

        replay_rows = detail.get("replay_videos", []) if isinstance(detail.get("replay_videos"), list) else []
        if str(detail.get("type") or "") == ActivityType.LESSON.value:
            replay_rows = [
                one for one in replay_rows
                if isinstance(one, dict) and str(one.get("label") or "") in {"ENCODER", "INSTRUCTOR"}
            ]
        else:
            replay_rows = []
        self._setReplayRows(replay_rows)

    def reset(self) -> None:
        """重置详情页到默认提示状态。

        :return: 无返回值。
        """
        self.detailTitleLabel.setText("-")
        self._setMetaItems([(FluentIcon.INFO, self.tr("提示"), self.tr("请选择一个活动查看详情"))])
        self._relatedLessonStartTime = None
        self.openRelatedLessonButton.setVisible(False)
        self._setDescriptionContent(None)
        self.detailUploadsTitle.setVisible(False)
        self._populateUploadTable(self.detailUploadsTable, [])
        self._setSubmissionRows([])
        self._setReplayRows([])
        self.setPageStatus(PageStatus.NORMAL)

    def _setSubmissionRows(self, submissions: list[dict]) -> None:
        """渲染“每次提交”区域。"""
        rows = [one for one in submissions if isinstance(one, dict)]
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

    def _setReplayRows(self, replay_videos: list[dict]) -> None:
        """渲染“课程回放视频”区域。"""
        rows = [one for one in replay_videos if isinstance(one, dict)]
        self.detailReplayTable.setRowCount(len(rows))
        for row, video in enumerate(rows):
            text = format_replay_video_label(video.get("label"))
            self.detailReplayTable.setItem(row, 0, QTableWidgetItem(text))
            self.detailReplayTable.setItem(row, 1, QTableWidgetItem(format_size(video.get("size"))))

            view_btn = PushButton(self.tr("在线播放"), self.detailReplayTable)
            view_btn.clicked.connect(lambda _=False, one=video: self.replayVideoViewRequested.emit(one))
            self.detailReplayTable.setCellWidget(row, 2, view_btn)

            save_btn = PushButton(self.tr("另存为"), self.detailReplayTable)
            save_btn.clicked.connect(lambda _=False, one=video: self.downloadRequested.emit(one))
            self.detailReplayTable.setCellWidget(row, 3, save_btn)

        visible = len(rows) > 0
        self.detailReplayLabel.setVisible(visible)
        self.detailReplayTable.setVisible(visible)
        self.detailReplayTable.resizeRowsToContents()
        self.detailReplayWarning.setVisible(visible)
        update_table_height(self.detailReplayTable, min_rows=0, min_height=38)

    def _populateUploadTable(self, table: TableWidget, uploads: list[dict]) -> int:
        """渲染附件表格并返回附件数量。"""
        rows = [one for one in uploads if isinstance(one, dict)]
        table.setRowCount(len(rows))
        table.setColumnWidth(2, ATTACHMENT_ACTION_COLUMN_WIDTH)
        for row, upload in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(safe_text(upload.get("name"))))
            table.setItem(row, 1, QTableWidgetItem(format_size(upload.get("size"))))

            actions = QWidget(table)
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(8)

            if can_preview_as_image(upload):
                preview_btn = PushButton(self.tr("预览"), actions)
                preview_btn.setFixedWidth(ATTACHMENT_ACTION_BUTTON_WIDTH)
                preview_btn.clicked.connect(lambda _=False, one=upload, all_rows=rows: self.previewRequested.emit(one, all_rows))
                action_layout.addWidget(preview_btn)
            else:
                spacer = QWidget(actions)
                spacer.setFixedWidth(ATTACHMENT_ACTION_BUTTON_WIDTH)
                action_layout.addWidget(spacer)

            save_btn = PushButton(self.tr("另存为"), actions)
            save_btn.setFixedWidth(ATTACHMENT_ACTION_BUTTON_WIDTH)
            save_btn.clicked.connect(lambda _=False, one=upload: self.downloadRequested.emit(one))
            action_layout.addWidget(save_btn)
            action_layout.addStretch(1)
            table.setCellWidget(row, 2, actions)

        table.resizeRowsToContents()
        update_table_height(table, min_rows=0, min_height=38)
        return len(rows)

    def _setMetaItems(self, items: list[MetaItem]) -> None:
        """重建标题下方的信息卡片区域。"""
        self._clearMetaItems()
        for icon, title, value in items:
            card = DetailMetaCard(icon, title, value, self.detailMetaHost)
            self.detailMetaLayout.addWidget(card)
            self._metaCards.append(card)
        self.detailMetaHost.setVisible(bool(items))
        self.detailMetaHost.adjustSize()

    def _setRelatedLessonButton(self, detail: dict) -> None:
        """根据当前详情决定是否显示“打开对应回放”按钮。"""
        lesson_start_time = detail.get("external_live_start_time") or detail.get("start_time")
        is_lecture_live = str(detail.get("type") or "") == ActivityType.LECTURE_LIVE.value
        if is_lecture_live and isinstance(lesson_start_time, str) and lesson_start_time:
            self._relatedLessonStartTime = lesson_start_time
            self.openRelatedLessonButton.setVisible(True)
            return

        self._relatedLessonStartTime = None
        self.openRelatedLessonButton.setVisible(False)

    def _clearMetaItems(self) -> None:
        """清理已渲染的信息卡片。"""
        for card in self._metaCards:
            self.detailMetaLayout.removeWidget(card)
            card.deleteLater()
        self._metaCards.clear()

    def _setDescriptionContent(self, rich_text: Optional[str]) -> None:
        """写入活动说明并同步描述卡片显隐。"""
        text = safe_text(rich_text)
        if text == "-":
            self.detailDescriptionLabel.clear()
            self.detailDescriptionLabel.setStyleSheet("")
            self.detailDescriptionCard.setVisible(False)
            return

        has_content = set_html_label(self.detailDescriptionLabel, text)
        self.detailDescriptionCard.setVisible(has_content)

    def _extractRichText(self, detail: dict) -> Optional[str]:
        """提取当前活动的说明文本。"""
        type_name = str(detail.get("type") or "")
        if type_name in {ActivityType.HOMEWORK.value, ActivityType.MATERIAL.value}:
            text = safe_text(detail.get("description"))
            return None if text == "-" else text
        return None

    def _buildDetailMetaItems(self, detail: dict) -> list[MetaItem]:
        """根据活动类型构建标题下方的信息提示项。"""
        type_name = str(detail.get("type") or "")
        items: list[MetaItem] = []

        if type_name == ActivityType.HOMEWORK.value:
            time_item = self._buildTimeMetaItem(detail.get("start_time"), detail.get("end_time"))
            if time_item is not None:
                items.append((FluentIcon.DATE_TIME, *time_item))

            submit_by_group = detail.get("submit_by_group")
            if isinstance(submit_by_group, bool):
                items.append((
                    FluentIcon.PEOPLE,
                    self.tr("提交方式"),
                    self.tr("小组") if submit_by_group else self.tr("个人"),
                ))

            self._appendMetaItem(items, FluentIcon.SPEED_HIGH, self.tr("最高分"), detail.get("highest_score"))
            self._appendMetaItem(items, FluentIcon.SPEED_OFF, self.tr("最低分"), detail.get("lowest_score"))
            self._appendMetaItem(items, FluentIcon.PIE_SINGLE, self.tr("平均分"), detail.get("average_score"))
            return items

        if type_name == ActivityType.LESSON.value:
            created_text = self._normalizedMetaText(detail.get("created_at"), is_time=True)
            if created_text is not None:
                items.append((FluentIcon.HISTORY, self.tr("创建时间"), created_text))
            return items

        if type_name == ActivityType.MATERIAL.value:
            time_item = self._buildTimeMetaItem(detail.get("start_time"), detail.get("end_time"))
            if time_item is not None:
                items.append((FluentIcon.DATE_TIME, *time_item))
            return items

        if type_name == ActivityType.LECTURE_LIVE.value:
            time_item = self._buildTimeMetaItem(detail.get("start_time"), detail.get("end_time"))
            if time_item is not None:
                items.append((FluentIcon.DATE_TIME, *time_item))

            live_room = format_live_room(detail.get("live_room"))
            if live_room != "-":
                items.append((FluentIcon.VIDEO, self.tr("直播间"), live_room))
            return items

        type_text = activity_type_text(detail.get("type"))
        if type_text != "-":
            items.append((FluentIcon.TAG, self.tr("类型"), type_text))

        time_item = self._buildTimeMetaItem(detail.get("start_time"), detail.get("end_time"))
        if time_item is not None:
            items.append((FluentIcon.DATE_TIME, *time_item))
        return items

    def _appendMetaItem(self, items: list[MetaItem], icon: FluentIcon, title: str, value: object) -> None:
        """在值有效时向信息列表追加一个展示项。"""
        text = self._normalizedMetaText(value)
        if text is not None:
            items.append((icon, title, text))

    def _normalizedMetaText(self, value: object, is_time: bool = False) -> Optional[str]:
        """将元信息值规范化为可展示文本。"""
        text = time_text(value) if is_time else safe_text(value)
        return None if text == "-" else text

    def _buildTimeMetaItem(self, start_value: object, end_value: object) -> Optional[tuple[str, str]]:
        """按活动卡片相同的省略逻辑生成时间展示项。"""
        start_text = time_text(start_value)
        end_text = time_text(end_value)

        if start_text != "-" and end_text != "-":
            return self.tr("时间"), self.tr("{} ~ {}").format(start_text, end_text)
        if end_text != "-":
            return self.tr("截止"), end_text
        if start_text != "-":
            return self.tr("开始"), start_text
        return None

    def _onOpenRelatedLessonClicked(self) -> None:
        """在用户点击按钮时请求主容器查找对应回放。"""
        if isinstance(self._relatedLessonStartTime, str) and self._relatedLessonStartTime:
            self.relatedLessonRequested.emit(self._relatedLessonStartTime)
