from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QCheckBox, QListWidget, QListWidgetItem, QFileDialog)
from ...threads.LMSArchiveThread import LMSArchiveThread
from ...sessions.session_backend import AccessMode
from ...utils import accounts
from auth import getVPNUrl
from lms.archive_service import archive_root


class LMSArchiveDialog(QDialog):
    """Preview a fixed account/course plan before downloading selected files."""
    def __init__(self, account, course, title, parent=None):
        super().__init__(parent)
        self.account, self.course = account, int(course)
        self.job = None
        self.invalid = False
        self.items = []
        self.setWindowTitle(self.tr('课程资料归档 — ') + title)
        self.resize(760, 540)
        layout = QVBoxLayout(self)
        label = QLabel(self.tr('先扫描当前课程，再勾选文件下载。包含活动附件、正文附件和作业附件；可选录像与回放。'), self)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.videos = QCheckBox(self.tr('包含录像与回放（可能较大）'), self)
        self.organize = QCheckBox(self.tr('按章节归档附件'), self)
        self.organize.setChecked(True)
        layout.addWidget(self.videos)
        layout.addWidget(self.organize)
        self.list = QListWidget(self)
        layout.addWidget(self.list)
        self.status = QLabel(self.tr('扫描仅获取资源信息，不下载文件。'), self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.scanButton = QPushButton(self.tr('扫描预览'), self)
        self.downloadButton = QPushButton(self.tr('下载所选…'), self)
        self.cancelButton = QPushButton(self.tr('取消任务'), self)
        self.closeButton = QPushButton(self.tr('关闭'), self)
        for button in (self.scanButton, self.downloadButton, self.cancelButton, self.closeButton):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.scanButton.clicked.connect(self.scan)
        self.downloadButton.clicked.connect(self.download)
        self.cancelButton.clicked.connect(self.cancel)
        self.closeButton.clicked.connect(self.reject)
        self.videos.toggled.connect(self.invalidate_plan)
        accounts.currentAccountChanged.connect(self.account_changed)
        self.refresh()

    def refresh(self):
        available = self.job is None and not self.invalid
        self.scanButton.setEnabled(available)
        self.downloadButton.setEnabled(available and bool(self.items))
        self.videos.setEnabled(available)
        self.organize.setEnabled(available)
        self.list.setEnabled(available)
        self.cancelButton.setEnabled(self.job is not None)
        self.closeButton.setEnabled(self.job is None)

    def invalidate_plan(self):
        self.items = []
        self.list.clear()
        self.refresh()

    def account_changed(self):
        self.invalid = True
        self.cancel()
        self.status.setText(self.tr('账户已切换，请关闭后从当前账户重新打开。'))
        self.refresh()

    def cancel(self):
        if self.job is not None:
            self.job.cancel()
            self.status.setText(self.tr('正在停止，请等待当前网络请求结束…'))

    def scan(self):
        if self.job is not None or self.invalid:
            return
        self.invalidate_plan()
        self.start(videos=self.videos.isChecked())

    def download(self):
        if self.job is not None or self.invalid:
            return
        selected = [item for i, item in enumerate(self.items)
                    if self.list.item(i).checkState() == Qt.Checked and not item.get('error')]
        if not selected:
            self.status.setText(self.tr('请勾选至少一个可下载资源。'))
            return
        target = QFileDialog.getExistingDirectory(self, self.tr('选择归档位置'))
        if not target:
            return
        try:
            root = archive_root(target, self.account.uuid, self.course)
            self.start(items=selected, root=root, organize=self.organize.isChecked())
        except Exception as exc:
            self.status.setText(str(exc))

    def start(self, **options):
        if self.job is not None or self.invalid:
            return
        try:
            session = self.account.session_manager.get_session('lms')
            if not session.has_login:
                raise ValueError('请先在思源学堂页面登录并打开课程，再扫描归档')
            rewrite = getVPNUrl if session.access_mode == AccessMode.WEBVPN else lambda url: url
            self.job = LMSArchiveThread(session, self.course, rewrite=rewrite, parent=self, **options)
            self.job.result.connect(self.on_result)
            self.job.progress.connect(self.on_progress)
            self.job.finished.connect(self.on_finished)
            self.refresh()
            self.status.setText(self.tr('正在处理…'))
            self.job.start()
        except Exception as exc:
            if self.job is not None and not self.job.isRunning():
                self.job.opener.close()
                self.job.deleteLater()
                self.job = None
            self.refresh()
            self.status.setText(str(exc))

    def on_progress(self, message):
        if not self.invalid and self.sender() is self.job:
            self.status.setText(message)

    def on_result(self, result):
        if self.invalid or (self.sender() is not None and self.sender() is not self.job):
            return
        if 'items' in result:
            self.items = result['items']
            self.list.clear()
            failed = 0
            for item in self.items:
                error = item.get('error')
                failed += bool(error)
                label = f'{item["kind"]} · {item["activity"]} · {item["name"]}'
                if error:
                    label += ' — ' + item.get('err_msg', '扫描失败')
                row = QListWidgetItem(label, self.list)
                row.setFlags(Qt.ItemIsEnabled | (Qt.ItemIsUserCheckable if not error else Qt.NoItemFlags))
                row.setCheckState(Qt.Unchecked if error else Qt.Checked)
            self.status.setText(f'发现 {len(self.items) - failed} 项资源；{failed} 项扫描失败。请核对清单后下载。')
        else:
            self.status.setText(result.get('message', '任务失败'))

    def on_finished(self):
        if self.job is None or (self.sender() is not None and self.sender() is not self.job):
            return
        self.job.deleteLater()
        self.job = None
        self.refresh()

    def reject(self):
        if self.job is not None:
            self.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)
