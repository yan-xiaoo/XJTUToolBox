from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import BodyLabel, ComboBox

from jwxt.calendar import SchoolCalendar
from .components.CampusPage import CampusPage
from .utils import accounts


class SchoolCalendarInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("schoolCalendarInterface", "校历", "学期起止与节假日", parent)
        self.terms = []
        self._auto_loaded = False

        self.termBox = ComboBox(self.view)
        self.termBox.setMinimumWidth(280)
        self.termBox.currentIndexChanged.connect(self._show_term)
        self.add_toolbar(self.labeled(self.tr("学期"), self.termBox))

        self.summary = BodyLabel(self.tr("打开本页会自动加载校历。"), self.view)
        self.summary.setWordWrap(True)
        self.vBoxLayout.addWidget(self.summary)
        self.table = self.make_table([self.tr("假期"), self.tr("开始"), self.tr("结束"), self.tr("天数")])
        self.vBoxLayout.addWidget(self.table, 1)

    def on_account_changed(self):
        self._auto_loaded = False
        self.terms = []
        self.termBox.blockSignals(True)
        self.termBox.clear()
        self.termBox.blockSignals(False)
        self.summary.setText(self.tr("打开本页会自动加载校历。"))
        self.table.setRowCount(0)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.load_terms()

    def load_terms(self):
        if not self.require_account():
            self._auto_loaded = False
            return
        self.start_job(
            "jwxt",
            self.tr("正在登录教务系统..."),
            lambda session: SchoolCalendar(session).get_terms(),
            self._on_terms,
        )

    def _on_terms(self, terms):
        self.terms = terms
        self.termBox.blockSignals(True)
        self.termBox.clear()
        self.table.setRowCount(0)
        self.summary.setText(self.tr("没有可显示的校历数据。"))
        for term in terms:
            self.termBox.addItem(f"{term.year_num} {term.term_num}")
        self.termBox.blockSignals(False)
        if terms:
            self._show_term(0)
        self.success(self.tr("查询成功"), self.tr("已加载校历"))

    def _show_term(self, index: int):
        if index < 0 or index >= len(self.terms):
            return
        term = self.terms[index]
        if term.current_week is None:
            self.summary.setText(
                self.tr("{start} 至 {end}，共 {weeks} 周").format(
                    start=term.start_date, end=term.end_date, weeks=term.week_number,
                )
            )
        else:
            self.summary.setText(
                self.tr("{start} 至 {end}，共 {weeks} 周，当前约第 {current} 周").format(
                    start=term.start_date, end=term.end_date, weeks=term.week_number, current=term.current_week,
                )
            )
        self.table.setRowCount(len(term.holidays))
        for row, holiday in enumerate(term.holidays):
            self.table.setItem(row, 0, QTableWidgetItem(holiday.name))
            self.table.setItem(row, 1, QTableWidgetItem(holiday.start_date))
            self.table.setItem(row, 2, QTableWidgetItem(holiday.end_date))
            self.table.setItem(row, 3, QTableWidgetItem(holiday.days))
