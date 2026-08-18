from PyQt5.QtWidgets import QFileDialog
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton

from dzpz import WORKFLOW_MAP, Transcript
from .components.CampusPage import CampusPage
from .utils import accounts


class TranscriptInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("transcriptInterface", "电子成绩单", "生成并下载盖章 PDF 成绩单", parent)
        self.form_ctx = None
        self._auto_loaded = False

        self.workflowBox = ComboBox(self.view)
        self.workflowBox.setMinimumWidth(160)
        for name, workflow_id in WORKFLOW_MAP.items():
            self.workflowBox.addItem(name, userData=workflow_id)
        self.typeBox = ComboBox(self.view)
        self.typeBox.setMinimumWidth(240)
        self.exportButton = PrimaryPushButton(self.tr("生成并下载"), self.view)
        self.exportButton.clicked.connect(self.export_pdf)
        self.add_toolbar(
            self.labeled(self.tr("流程"), self.workflowBox, width=40),
            self.labeled(self.tr("类型"), self.typeBox, width=40),
            self.exportButton,
        )
        self.hint = BodyLabel(self.tr("打开本页会自动加载成绩单类型，选好后即可生成 PDF。"), self.view)
        self.hint.setWordWrap(True)
        self.vBoxLayout.addWidget(self.hint)
        self.vBoxLayout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.load_types()

    def load_types(self):
        if not self.require_account():
            self._auto_loaded = False
            return
        workflow_id = self.workflowBox.currentData()
        self.start_job(
            "dzpz",
            self.tr("正在加载成绩单类型..."),
            lambda session: Transcript(session).load_create_form(workflow_id),
            self._on_types,
        )

    def _on_types(self, ctx):
        self.form_ctx = ctx
        self.typeBox.clear()
        for option in ctx.type_options:
            self.typeBox.addItem(option.name, userData=option.value)
        self.success(self.tr("加载成功"), self.tr("已更新成绩单类型"))

    def export_pdf(self):
        if not self.require_account():
            return
        workflow_id = self.workflowBox.currentData()
        type_value = self.typeBox.currentData()
        if type_value is None:
            self.warn(self.tr("未选择类型"), self.tr("成绩单类型还没加载完"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("保存成绩单"),
            f"{getattr(accounts.current, 'username', 'transcript')}.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return

        def worker(session):
            info, content = Transcript(session).generate_and_download(workflow_id, type_value)
            with open(path, "wb") as handle:
                handle.write(content)
            return info, path

        self.start_job("dzpz", self.tr("正在生成电子成绩单..."), worker, self._on_exported)

    def _on_exported(self, payload):
        info, path = payload
        self.hint.setText(self.tr("已保存 {name} 到 {path}").format(name=info.filename, path=path))
        self.success(self.tr("下载成功"), info.filename)
