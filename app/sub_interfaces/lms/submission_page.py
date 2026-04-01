from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy, QTableWidgetItem, QWidget, QHBoxLayout
from qfluentwidgets import PushButton, TableWidget, TitleLabel

from .common import create_section_title, update_table_height, set_html_label, safe_text, \
    format_size, apply_stretch_on_first_column, can_preview_as_image, has_attachment_review_by_rules, \
    ATTACHMENT_ACTION_BUTTON_WIDTH, ATTACHMENT_ACTION_COLUMN_WIDTH


class LMSSubmissionPage(QFrame):
    # 用户点击下载按钮后，通知主容器执行下载。
    downloadRequested = pyqtSignal(dict)
    # 用户点击图片预览后，通知主容器打开预览对话框。
    previewRequested = pyqtSignal(dict, list)
    # 用户点击批改预览后，通知主容器打开带批注叠加的预览对话框。
    reviewPreviewRequested = pyqtSignal(dict, list, list)
    # 用户点击调试按钮后，通知主容器将当前提交的批注映射输出到控制台。
    markedAttachmentsDebugRequested = pyqtSignal()

    def __init__(self, parent=None):
        """初始化提交详情页组件。"""
        super().__init__(parent)
        self.setObjectName("submissionPage")

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(12, 8, 12, 20)
        layout.setAlignment(Qt.AlignTop)

        self.submissionTitleLabel = TitleLabel("-", self)
        self.submissionTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.debugMarkedAttachmentsButton = PushButton(self.tr("输出批注映射"), self)
        self.debugMarkedAttachmentsButton.setMinimumWidth(144)
        self.debugMarkedAttachmentsButton.clicked.connect(self.markedAttachmentsDebugRequested.emit)
        self.debugMarkedAttachmentsButton.setVisible(False)

        self.titleRow = QWidget(self)
        self.titleRowLayout = QHBoxLayout(self.titleRow)
        self.titleRowLayout.setContentsMargins(0, 0, 0, 0)
        self.titleRowLayout.setSpacing(12)
        self.titleRowLayout.addWidget(self.submissionTitleLabel)
        self.titleRowLayout.addStretch(1)
        self.titleRowLayout.addWidget(self.debugMarkedAttachmentsButton)

        self.submissionCommentTitle = create_section_title(self, self.tr("作业文字内容"))
        self.submissionCommentTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionCommentLabel = QLabel(self)
        self.submissionCommentLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionCommentLabel.setWordWrap(True)
        self.submissionCommentLabel.setOpenExternalLinks(True)
        self.submissionCommentLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionInstructorTitle = create_section_title(self, self.tr("老师批语"))
        self.submissionInstructorTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionInstructorLabel = QLabel(self)
        self.submissionInstructorLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.submissionInstructorLabel.setWordWrap(True)
        self.submissionInstructorLabel.setOpenExternalLinks(True)
        self.submissionInstructorLabel.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        self.submissionUploadsTitle = create_section_title(self, self.tr("本次提交附件"))
        self.submissionUploadsTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionUploadsTable = self._createUploadTable()
        self.submissionUploadsTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout.addWidget(self.titleRow)
        layout.addWidget(self.submissionCommentTitle)
        layout.addWidget(self.submissionCommentLabel)
        layout.addWidget(self.submissionInstructorTitle)
        layout.addWidget(self.submissionInstructorLabel)
        layout.addWidget(self.submissionUploadsTitle)
        layout.addWidget(self.submissionUploadsTable)

    def _createUploadTable(self) -> TableWidget:
        """创建提交详情页使用的附件表格。"""
        table = TableWidget(self)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels([self.tr("名称"), self.tr("大小"), self.tr("另存为")])
        apply_stretch_on_first_column(table)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setEditTriggers(TableWidget.NoEditTriggers)
        table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        return table

    def setSubmission(self, submission: dict, course_name: str, activity_name: str):
        """填充提交详情页数据。

        :param submission: 单次提交详情字典。
        :param course_name: 当前课程名称，用于标题展示。
        :param activity_name: 当前活动名称，用于标题展示。
        :return: 无返回值。
        """
        self.submissionTitleLabel.setText(f"{activity_name}")
        # 这个批注映射似乎不该展示给用户。暂时注释掉显示 Button 的代码。
        # self.debugMarkedAttachmentsButton.setVisible(isinstance(submission.get("id"), int))

        has_comment = set_html_label(self.submissionCommentLabel, submission.get("comment"))
        self.submissionCommentTitle.setVisible(has_comment)
        self.submissionCommentLabel.setVisible(has_comment)

        has_instructor = set_html_label(self.submissionInstructorLabel, submission.get("instructor_comment"))
        self.submissionInstructorTitle.setVisible(has_instructor)
        self.submissionInstructorLabel.setVisible(has_instructor)

        sub_uploads = submission.get("uploads", []) if isinstance(submission.get("uploads"), list) else []
        sub_upload_count = self._populateUploadTable(
            self.submissionUploadsTable,
            sub_uploads,
            review_context_uploads=sub_uploads,
            marked_data=submission.get("marked_attachments") if isinstance(submission, dict) else None,
        )
        self.submissionUploadsTitle.setVisible(sub_upload_count > 0)
        self.submissionUploadsTable.setVisible(sub_upload_count > 0)

        QTimer.singleShot(0, self._refreshUploadTableHeights)

    def reset(self):
        """重置提交详情页到空状态。

        :return: 无返回值。
        """
        self.submissionTitleLabel.setText("-")
        self.debugMarkedAttachmentsButton.setVisible(False)
        self.submissionCommentLabel.clear()
        self.submissionInstructorLabel.clear()
        self._populateUploadTable(self.submissionUploadsTable, [])
        self.submissionCommentTitle.setVisible(False)
        self.submissionCommentLabel.setVisible(False)
        self.submissionInstructorTitle.setVisible(False)
        self.submissionInstructorLabel.setVisible(False)
        self.submissionUploadsTitle.setVisible(False)
        self.submissionUploadsTable.setVisible(False)

    def _populateUploadTable(
        self,
        table: TableWidget,
        uploads,
        review_context_uploads: list[dict] | None = None,
        marked_data: dict | None = None,
    ) -> int:
        """渲染附件表格并返回附件数量。"""
        rows = [one for one in uploads if isinstance(one, dict)] if isinstance(uploads, list) else []
        review_source_rows = (
            [one for one in review_context_uploads if isinstance(one, dict)]
            if isinstance(review_context_uploads, list) else rows
        )
        table.setRowCount(len(rows))
        table.setColumnWidth(2, ATTACHMENT_ACTION_COLUMN_WIDTH)
        for row, upload in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(safe_text(upload.get("name"))))
            table.setItem(row, 1, QTableWidgetItem(format_size(upload.get("size"))))

            actions = QWidget(table)
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(8)

            if has_attachment_review_by_rules(upload, marked_data):
                mark_btn = PushButton(self.tr("批改预览"), actions)
                mark_btn.setFixedWidth(ATTACHMENT_ACTION_BUTTON_WIDTH)
                mark_btn.clicked.connect(
                    lambda _=False, one=upload, all_rows=rows, review_rows=review_source_rows:
                    self.reviewPreviewRequested.emit(one, all_rows, review_rows)
                )
                action_layout.addWidget(mark_btn)
            else:
                spacer = QWidget(actions)
                spacer.setFixedWidth(ATTACHMENT_ACTION_BUTTON_WIDTH)
                action_layout.addWidget(spacer)

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

    def _refreshUploadTableHeights(self):
        """刷新可见附件表格高度，确保布局正确。"""
        for table in (self.submissionUploadsTable,):
            if table.isVisible():
                table.resizeRowsToContents()
                update_table_height(table, min_rows=0, min_height=38)
