import os.path

from PyQt5.QtCore import pyqtSlot, QStandardPaths
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QFileDialog
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, PushButton, LineEdit, CheckBox, ToolTipFilter, ToolTipPosition


class ExportCalendarDialog(MessageBoxBase):
    """
    导出日历为 ics 文件的对话框
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.result_path = None
        self.ignore_holiday = True
        self.set_alarm = True

        self.title = TitleLabel(self.tr("导出课程表"), self)
        self.hint = CaptionLabel(self.tr("导出课程表为 ics 日历文件"), self)

        self.fileFrame = QFrame(self)
        self.fileLayout = QHBoxLayout()

        self.fileEdit = LineEdit(self)
        self.fileEdit.setPlaceholderText(self.tr("选择导出位置"))
        self.fileButton = PushButton(self.tr("浏览..."), self)
        self.fileButton.clicked.connect(self._onChooseFileButtonClicked)
        self.fileLayout.addWidget(self.fileEdit)
        self.fileLayout.addWidget(self.fileButton)
        self.fileFrame.setLayout(self.fileLayout)

        self.skipCheck = CheckBox(self.tr("忽略节假日的课程"), self)
        self.skipCheck.setChecked(True)
        self.skipCheck.setToolTip(self.tr("由于 Ehall 课表错误，法定节假日可能会错误的存在课程，勾选此项将忽略这些课程"))
        self.skipCheck.setToolTipDuration(10000)
        self.skipCheck.installEventFilter(ToolTipFilter(self.skipCheck, showDelay=1000, position=ToolTipPosition.TOP))

        self.alarmCheck = CheckBox(self.tr("设置提醒事项"), self)
        self.alarmCheck.setChecked(True)
        self.alarmCheck.setToolTip(self.tr("在课程开始前 15 分钟提醒，考试开始前 30 分钟提醒"))
        self.alarmCheck.setToolTipDuration(10000)
        self.alarmCheck.installEventFilter(ToolTipFilter(self.alarmCheck, showDelay=1000, position=ToolTipPosition.TOP))

        self.hintLabel = CaptionLabel(self.tr("日历包含本学期所有课程，但不包含考勤状态\n日历不包含调休日的课程"), self)

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.fileFrame)
        self.viewLayout.addWidget(self.skipCheck)
        self.viewLayout.addWidget(self.alarmCheck)
        self.viewLayout.addWidget(self.hintLabel)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

    @pyqtSlot()
    def _onYesButtonClicked(self):
        file_path = self.fileEdit.text()
        if not os.path.exists(os.path.dirname(file_path)) or os.path.isdir(file_path):
            self.fileEdit.setError(True)
            self.fileEdit.setFocus()
            return

        self.result_path = file_path
        self.ignore_holiday = self.skipCheck.isChecked()
        self.set_alarm = self.alarmCheck.isChecked()
        self.accept()

    @pyqtSlot()
    def _onChooseFileButtonClicked(self):
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("导出为 ics"), filter=self.tr("iCalendar (*.ics);;所有文件 (*)"),
                                                   directory=QStandardPaths.writableLocation(QStandardPaths.DesktopLocation))
        if file_path:
            self.fileEdit.setText(file_path)
