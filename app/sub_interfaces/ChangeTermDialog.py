import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from qfluentwidgets import MessageBoxBase, TitleLabel, CaptionLabel, EditableComboBox


class ChangeTermDialog(MessageBoxBase):
    """课表界面中，选择更多-修改学期弹出的对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)

        self.title = TitleLabel(self.tr("修改学期"), self)
        self.hint = CaptionLabel(self.tr("请选择或输入学期编号"), self)
        self.termBox = EditableComboBox(self)
        self.failHint = CaptionLabel(self)
        self.failHint.setVisible(False)
        self.failHint.setTextColor(QColor(255, 0, 0), QColor(255, 0, 0))

        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)
        self.viewLayout.addWidget(self.termBox)
        self.viewLayout.addWidget(self.failHint)

        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onYesButtonClicked)

        self.term_number = None

        current_date = datetime.date.today()
        # 七月之后为上半学期，显示前推三年的学期和当前这个上半学期
        if current_date.month >= 7:
            for year in range(current_date.year - 3, current_date.year):
                self.termBox.addItem(f"{year}-{year + 1}-1")
                self.termBox.addItem(f"{year}-{year + 1}-2")
                self.termBox.addItem(f"{year}-{year + 1}-3")
            self.termBox.addItem(f"{current_date.year}-{current_date.year + 1}-1")
            # 设置编号为当前学期
            if current_date.month < 8:
                self.termBox.setCurrentIndex(8)
            else:
                self.termBox.setCurrentIndex(9)
        # 七月之前为下半学期，显示前推四年的学期和当前整年
        else:
            for year in range(current_date.year - 4, current_date.year):
                self.termBox.addItem(f"{year}-{year + 1}-1")
                self.termBox.addItem(f"{year}-{year + 1}-2")
                self.termBox.addItem(f"{year}-{year + 1}-3")
            if current_date.month <= 1:
                self.termBox.setCurrentIndex(9)
            else:
                self.termBox.setCurrentIndex(10)
        # 系统中有数据的最新学期
        self.max_term_number = self.termBox.items[-1].text

    def showError(self, text):
        # 在输入错误时，将输入框标记为错误，并显示错误提示
        self.termBox.setError(True)
        self.failHint.setText(text)
        self.failHint.setVisible(True)

    def keyReleaseEvent(self, a0):
        super().keyReleaseEvent(a0)
        if a0.key() == Qt.Key_Return:
            self._onYesButtonClicked()
        elif a0.key() == Qt.Key_Escape:
            self.cancelButton.click()

    def _onYesButtonClicked(self):
        if not self.termBox.text():
            self.termBox.setError(True)
            return
        else:
            term_number = self.termBox.currentText()
            correct = True
            try:
                start, end, no = map(int, term_number.split("-"))
            except (ValueError, TypeError):
                correct = False
                self.showError(self.tr("学期编号格式错误，示例: 2020-2021-1"))
            else:
                if no not in (1, 2, 3):
                    correct = False
                    self.showError(self.tr("学期编号最后一位必须为 1、2 或 3"))
                elif start >= end:
                    correct = False
                    self.showError(self.tr("结束年份必须大于开始年份"))
                elif start < 2016 or term_number > self.max_term_number:
                    correct = False
                    self.showError(self.tr("学期编号超出可查询范围"))
            if not correct:
                return

            # 设置结果
            self.term_number = term_number
            self.accept()
            self.accepted.emit()
