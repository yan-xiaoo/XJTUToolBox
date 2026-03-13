from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy, QTableWidgetItem
from qfluentwidgets import PushButton, TableWidget, TitleLabel

from .common import create_section_title, apply_default_column_width, update_table_height, set_html_label, safe_text, format_size


class LMSSubmissionPage(QFrame):
    # 用户点击下载按钮后，通知主容器执行下载。
    downloadRequested = pyqtSignal(dict)

    def __init__(self, parent=None):
        """初始化提交详情页组件。"""
        super().__init__(parent)
        self.setObjectName("submissionPage")

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignTop)

        self.submissionTitleLabel = TitleLabel("-", self)
        self.submissionTitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

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

        self.submissionCorrectTitle = create_section_title(self, self.tr("批阅附件"))
        self.submissionCorrectTitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.submissionCorrectTable = self._createUploadTable()
        self.submissionCorrectTable.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout.addWidget(self.submissionTitleLabel)
        layout.addWidget(self.submissionCommentTitle)
        layout.addWidget(self.submissionCommentLabel)
        layout.addWidget(self.submissionInstructorTitle)
        layout.addWidget(self.submissionInstructorLabel)
        layout.addWidget(self.submissionUploadsTitle)
        layout.addWidget(self.submissionUploadsTable)
        layout.addWidget(self.submissionCorrectTitle)
        layout.addWidget(self.submissionCorrectTable)

    def _createUploadTable(self) -> TableWidget:
        """创建提交详情页使用的附件表格。"""
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

    def setSubmission(self, submission: dict, course_name: str, activity_name: str):
        """填充提交详情页数据。

        :param submission: 单次提交详情字典。
        :param course_name: 当前课程名称，用于标题展示。
        :param activity_name: 当前活动名称，用于标题展示。
        :return: 无返回值。
        """
        self.submissionTitleLabel.setText(f"{course_name} / {activity_name}")

        has_comment = set_html_label(self.submissionCommentLabel, submission.get("comment"))
        self.submissionCommentTitle.setVisible(has_comment)
        self.submissionCommentLabel.setVisible(has_comment)

        has_instructor = set_html_label(self.submissionInstructorLabel, submission.get("instructor_comment"))
        self.submissionInstructorTitle.setVisible(has_instructor)
        self.submissionInstructorLabel.setVisible(has_instructor)

        sub_uploads = submission.get("uploads", []) if isinstance(submission.get("uploads"), list) else []
        sub_upload_count = self._populateUploadTable(self.submissionUploadsTable, sub_uploads)
        self.submissionUploadsTitle.setVisible(sub_upload_count > 0)
        self.submissionUploadsTable.setVisible(sub_upload_count > 0)

        submission_correct = submission.get("submission_correct", {}) if isinstance(submission.get("submission_correct"), dict) else {}
        correct_uploads = submission_correct.get("uploads", []) if isinstance(submission_correct.get("uploads"), list) else []
        correct_upload_count = self._populateUploadTable(self.submissionCorrectTable, correct_uploads)
        self.submissionCorrectTitle.setVisible(correct_upload_count > 0)
        self.submissionCorrectTable.setVisible(correct_upload_count > 0)

        QTimer.singleShot(0, self._refreshUploadTableHeights)

    def reset(self):
        """重置提交详情页到空状态。

        :return: 无返回值。
        """
        self.submissionTitleLabel.setText("-")
        self.submissionCommentLabel.clear()
        self.submissionInstructorLabel.clear()
        self._populateUploadTable(self.submissionUploadsTable, [])
        self._populateUploadTable(self.submissionCorrectTable, [])
        self.submissionCommentTitle.setVisible(False)
        self.submissionCommentLabel.setVisible(False)
        self.submissionInstructorTitle.setVisible(False)
        self.submissionInstructorLabel.setVisible(False)
        self.submissionUploadsTitle.setVisible(False)
        self.submissionUploadsTable.setVisible(False)
        self.submissionCorrectTitle.setVisible(False)
        self.submissionCorrectTable.setVisible(False)

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

    def _refreshUploadTableHeights(self):
        """刷新可见附件表格高度，确保布局正确。"""
        for table in (self.submissionUploadsTable, self.submissionCorrectTable):
            if table.isVisible():
                table.resizeRowsToContents()
                update_table_height(table, min_rows=0, min_height=38)
