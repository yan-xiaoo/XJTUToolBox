from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QButtonGroup
from qfluentwidgets import MessageBoxBase, BodyLabel, StrongBodyLabel, RadioButton, \
    CheckBox, PushButton, PrimaryPushButton, FluentIcon, LineEdit

from lms.models import ActivityType


class LMSBatchDownloadDialog(MessageBoxBase):
    """LMS 批量下载确认对话框。"""

    def __init__(
        self,
        activity_type: str,
        selected_activities: list[dict],
        course_name: str,
        total_count: int = 0,
        parent=None,
    ):
        """初始化批量下载确认对话框。

        :param activity_type: 当前活动类型（homework/material/lesson/lecture_live）。
        :param selected_activities: 用户选中的活动字典列表。
        :param course_name: 课程名称。
        :param total_count: 当前类型下的活动总数。
        :param parent: 父级控件。
        """
        super().__init__(parent)

        self.activity_type = activity_type
        self.selected_activities = [dict(a) for a in selected_activities if isinstance(a, dict)]
        self.course_name = course_name

        # 用户选择的结果
        self.layout_mode = "hierarchical"  # "flat" 或 "hierarchical"
        self.target_dir: Optional[str] = None
        self.download_uploads = True
        self.download_submissions = True
        self.download_marked = False

        self.setupUI(total_count)
        self._connectSignals()

    def setupUI(self, total_count: int):
        """构建对话框内容。"""
        self.contentWidget = QWidget(self)
        self.content_layout = QVBoxLayout(self.contentWidget)
        self.content_layout.setAlignment(Qt.AlignTop)

        # ---- 汇总信息 ----
        self.summaryLabel = BodyLabel(
            self.tr("课程：{0}").format(self.course_name),
            self.contentWidget,
        )

        activity_count = len(self.selected_activities)
        self.countLabel = BodyLabel(
            self.tr("选中活动 {0} 个，共 {1} 个").format(activity_count, total_count),
            self.contentWidget,
        )

        # ---- 下载位置 ----
        self.locationGroup = QButtonGroup(self.contentWidget)
        self.flatRadio = RadioButton(self.tr("统一存放"), self.contentWidget)
        self.hierarchicalRadio = RadioButton(self.tr("按活动存放"), self.contentWidget)
        self.hierarchicalRadio.setChecked(True)
        self.locationGroup.addButton(self.flatRadio)
        self.locationGroup.addButton(self.hierarchicalRadio)

        # ---- 目标目录 ----
        self.dirLayout = QHBoxLayout()
        self.dirEdit = LineEdit(self.contentWidget)
        self.dirEdit.setPlaceholderText(self.tr("选择目标目录..."))
        self.dirEdit.setMinimumWidth(280)
        self.dirEdit.setReadOnly(True)
        self.dirButton = PushButton(FluentIcon.FOLDER, self.tr("浏览..."), self.contentWidget)
        self.dirLayout.addWidget(self.dirEdit, stretch=1)
        self.dirLayout.addWidget(self.dirButton)

        # ---- 下载内容选项（仅对作业生效） ----
        is_homework = self.activity_type == ActivityType.HOMEWORK.value
        self.optionLabel = StrongBodyLabel(self.tr("下载内容"), self.contentWidget)
        self.uploadCheck = CheckBox(self.tr("作业附件"), self.contentWidget)
        self.submissionCheck = CheckBox(self.tr("提交附件"), self.contentWidget)
        self.markedCheck = CheckBox(self.tr("批阅附件"), self.contentWidget)
        self.uploadCheck.setChecked(True)
        self.submissionCheck.setChecked(True)
        self.optionLabel.setVisible(is_homework)
        self.uploadCheck.setVisible(is_homework)
        self.submissionCheck.setVisible(is_homework)
        self.markedCheck.setVisible(is_homework)

        # ---- 组装 ----
        self.content_layout.addWidget(self.summaryLabel)
        self.content_layout.addWidget(self.countLabel)

        self.content_layout.addSpacing(12)
        self.content_layout.addWidget(StrongBodyLabel(self.tr("下载位置"), self.contentWidget))
        self.content_layout.addWidget(self.flatRadio)
        self.content_layout.addWidget(self.hierarchicalRadio)

        self.content_layout.addSpacing(8)
        self.content_layout.addLayout(self.dirLayout)

        if is_homework:
            self.content_layout.addSpacing(12)
            self.content_layout.addWidget(self.optionLabel)
            self.content_layout.addWidget(self.uploadCheck)
            self.content_layout.addWidget(self.submissionCheck)
            self.content_layout.addWidget(self.markedCheck)

        self.viewLayout.addWidget(self.contentWidget)
        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(12, 12, 12, 12)
        self.viewLayout.setSizeConstraint(QVBoxLayout.SetFixedSize)

        self.yesButton.setText(self.tr("开始下载"))
        self.cancelButton.setText(self.tr("取消"))
        self.buttonGroup.setVisible(True)

    def _connectSignals(self):
        """连接信号。"""
        self.flatRadio.toggled.connect(
            lambda checked: self._onLocationChanged("flat" if checked else self.layout_mode)
        )
        self.hierarchicalRadio.toggled.connect(
            lambda checked: self._onLocationChanged("hierarchical" if checked else self.layout_mode)
        )
        self.dirButton.clicked.connect(self._onBrowseDir)
        self.uploadCheck.stateChanged.connect(self._onCheckChanged)
        self.submissionCheck.stateChanged.connect(self._onCheckChanged)
        self.markedCheck.stateChanged.connect(self._onCheckChanged)
        self.yesButton.clicked.connect(self._onConfirm)

    def _onLocationChanged(self, mode: str):
        self.layout_mode = mode

    def _onBrowseDir(self):
        """打开目录选择对话框。"""
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("选择下载目录"), self.dirEdit.text() or ""
        )
        if directory:
            self.target_dir = directory
            self.dirEdit.setText(directory)
            self.dirEdit.setError(False)

    def _onCheckChanged(self):
        """更新下载选项状态。"""
        self.download_uploads = self.uploadCheck.isChecked()
        self.download_submissions = self.submissionCheck.isChecked()
        self.download_marked = self.markedCheck.isChecked()

    def _onConfirm(self):
        """确认下载前检查参数完整性。"""
        if not self.target_dir:
            self.dirEdit.setError(True)
            self.dirEdit.setFocus()
            return
        self.accept()
