from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton

from fitness import Fitness
from .components.CampusPage import CampusPage
from .utils import accounts


class FitnessInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("fitnessInterface", "体测查询", "查询体测项目分与总评", parent)
        self.years = []
        self._auto_loaded = False

        self.yearBox = ComboBox(self.view)
        self.yearBox.setMinimumWidth(200)
        self.yearBox.currentIndexChanged.connect(self._on_year_changed)
        self.queryButton = PrimaryPushButton(self.tr("查询成绩"), self.view)
        self.queryButton.setFixedWidth(110)
        self.queryButton.clicked.connect(self.query_score)
        self.add_toolbar(self.labeled(self.tr("学年"), self.yearBox), self.queryButton)

        self.summary = BodyLabel(self.tr("打开本页会自动加载体测学年。"), self.view)
        self.vBoxLayout.addWidget(self.summary)
        self.table = self.make_table([self.tr("项目"), self.tr("成绩"), self.tr("等级"), self.tr("附加")])
        self.vBoxLayout.addWidget(self.table, 1)

    def on_account_changed(self):
        self._auto_loaded = False
        self.years = []
        self.yearBox.clear()
        self.summary.setText(self.tr("打开本页会自动加载体测学年。"))
        self.table.setRowCount(0)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.load_years()

    def load_years(self):
        if not self.require_account():
            self._auto_loaded = False
            return
        self.start_job("fitness", self.tr("正在登录体测系统..."), lambda session: Fitness(session).get_years(), self._on_years)

    def _on_years(self, years):
        self.years = years
        self.yearBox.blockSignals(True)
        self.yearBox.clear()
        for year in years:
            self.yearBox.addItem(year.name, userData=year.year_num)
            if year.checked:
                self.yearBox.setCurrentIndex(self.yearBox.count() - 1)
        self.yearBox.blockSignals(False)
        self.success(self.tr("查询成功"), self.tr("已加载体测学年"))
        if self.yearBox.currentData():
            self.query_score()

    def _on_year_changed(self, _index):
        if self.yearBox.currentData() and self._auto_loaded:
            self.query_score()

    def query_score(self):
        if not self.require_account():
            return
        year_num = self.yearBox.currentData()
        if not year_num:
            self.warn(self.tr("未选择学年"), self.tr("学年还没加载完，请稍后再查"))
            return
        self.start_job("fitness", self.tr("正在查询体测成绩..."), lambda session: Fitness(session).get_score(year_num), self._on_score)

    def _on_score(self, score):
        self.summary.setText(
            self.tr("{name}  {sno}  总分 {total}  等级 {grade}").format(
                name=score.student_name, sno=score.student_num, total=score.total_score, grade=score.total_grade,
            )
        )
        self.table.setRowCount(len(score.items))
        for row, item in enumerate(score.items):
            self.table.setItem(row, 0, QTableWidgetItem(item.name))
            self.table.setItem(row, 1, QTableWidgetItem(item.score))
            self.table.setItem(row, 2, QTableWidgetItem(item.grade))
            self.table.setItem(row, 3, QTableWidgetItem(item.extra))
        self.success(self.tr("查询成功"), self.tr("已更新体测成绩"))
