import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QDate, pyqtSignal
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, FastCalendarPicker


class TermStartTimeDialog(MessageBoxBase):
    """课表界面中，选择更多-修改学期开始时间弹出的对话框"""
    # 发送选择的日期
    dateSignal = pyqtSignal(datetime.date)

    def __init__(self, initial_date: datetime.date = None, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("设置学期开始时间"), self)
        self.hint = CaptionLabel(self.tr("请设置当前学期的开始时间（第一周周一的日期）"), self)

        self.calendar = FastCalendarPicker()
        self.calendar.setText(self.tr("选择日期"))
        if initial_date is not None:
            self.calendar.setDate(QDate(initial_date.year, initial_date.month, initial_date.day))

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.calendar)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

        # 结果日期
        self.date: Optional[datetime.date] = None

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    def _onYesButtonClicked(self):
        # 设置结果
        self.date = self.calendar.getDate().toPyDate()
        self.dateSignal.emit(self.date)
        self.accept()
        self.accepted.emit()
