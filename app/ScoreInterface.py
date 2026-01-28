import datetime
import json

from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, PrimaryPushButton, TableWidget, ToolTipFilter, \
    ToolTipPosition, InfoBar, InfoBarPosition, TransparentPushButton, CaptionLabel

from app.components.MultiSelectionComboBox import MultiSelectionComboBox
from app.sub_interfaces.ScoreDetailDialog import ScoreDetailDialog, EmptyScoreDetailDialog
from app.threads.GraduateScoreThread import GraduateScoreThread
from app.threads.ProcessWidget import ProcessWidget
from app.threads.ScoreThread import ScoreThread
from app.utils import StyleSheet, cfg, AccountDataManager, accounts


class ScoreInterface(ScrollArea):
    """成绩查询界面"""
    def __init__(self, parent=None):
        super().__init__(parent)

        self.view = QWidget(self)
        self.setObjectName("ScoreInterface")

        self.view.setObjectName("view")

        self.vBoxLayout = QVBoxLayout(self.view)

        self.titleLabel = TitleLabel(self.tr("成绩查询"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.minorLabel = StrongBodyLabel(self.tr("查询各个学期的成绩，并计算均分"), self.view)
        self.minorLabel.setContentsMargins(15, 5, 0, 0)
        self.vBoxLayout.addWidget(self.minorLabel)
        self.vBoxLayout.addSpacing(10)

        self.viewFrame = QFrame(self.view)
        self.viewLayout = QVBoxLayout(self.viewFrame)
        self.vBoxLayout.addWidget(self.viewFrame, stretch=1)

        self.commandFrame = QFrame(self.view)
        self.commandLayout = QHBoxLayout(self.commandFrame)

        self.termBox = MultiSelectionComboBox(all_select_option=True, parent=self.view)

        self.scoreButton = PrimaryPushButton(self.tr("查询"), self.view)
        self.scoreButton.setFixedHeight(40)
        self.commandLayout.addWidget(self.termBox, stretch=2)
        self.commandLayout.addWidget(self.scoreButton, stretch=1)

        self.scoreThread = ScoreThread()
        self.processWidget = ProcessWidget(self.scoreThread, self.view, stoppable=True, hide_on_end=True)
        self.processWidget.setVisible(False)
        self.scoreThread.error.connect(self.onThreadError)
        self.scoreThread.scores.connect(self.onReceiveScore)
        self.scoreThread.finished.connect(self.unlock)

        self.graduateScoreThread = GraduateScoreThread()
        self.graduateProcessWidget = ProcessWidget(self.graduateScoreThread, self.view, stoppable=True, hide_on_end=True)
        self.graduateProcessWidget.setVisible(False)
        self.graduateScoreThread.error.connect(self.onThreadError)
        self.graduateScoreThread.scores.connect(self.onReceiveScore)
        self.graduateScoreThread.finished.connect(self.unlock)

        self._onlyNotice = None
        self.scores = None

        self.statisticTable = TableWidget(self.view)
        self.statisticTable.setRowCount(1)
        self.statisticTable.setColumnCount(3)
        self.statisticTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.statisticTable.setHorizontalHeaderLabels([self.tr("总学分"), self.tr("平均绩点"), self.tr("平均分")])
        self.statisticTable.verticalHeader().setVisible(False)
        self.statisticTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        self.statisticTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.statisticTable.setMaximumHeight(75)

        self.scoreTable = TableWidget(self.view)
        # 随便先设置一个行数，后面会根据查询结果调整
        self.scoreTable.setToolTip(self.tr("单击选择课程以查看部分课程的统计信息"))
        self.scoreTable.setToolTipDuration(2500)
        self.scoreTable.setRowCount(7)
        self.scoreTable.setColumnCount(5)
        self.scoreTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.scoreTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.scoreTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.scoreTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.scoreTable.verticalHeader().setVisible(False)
        self.scoreTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.scoreTable.setSelectionMode(TableWidget.SelectionMode.MultiSelection)
        self.scoreTable.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)

        self.scoreTable.itemSelectionChanged.connect(self.onSelectScore)

        self.hintText = CaptionLabel(self.tr("单击选中几行课程，即可查看选中课程的均分信息"), self.view)
        self.hintText.setToolTip(self.tr("单击这条提示可以关闭它"))
        self.hintText.installEventFilter(ToolTipFilter(self.hintText))
        self.hintText.mouseReleaseEvent = lambda e: self.hintText.setVisible(False)

        self.scoreButton.clicked.connect(self.onScoreButtonClicked)

        self.viewLayout.addWidget(self.commandFrame)
        self.viewLayout.addWidget(self.processWidget)
        self.viewLayout.addWidget(self.graduateProcessWidget)
        self.viewLayout.addWidget(self.statisticTable)
        self.viewLayout.addWidget(self.scoreTable, stretch=1)
        self.viewLayout.addSpacing(5)
        self.viewLayout.addWidget(self.hintText, alignment=Qt.AlignmentFlag.AlignHCenter)

        StyleSheet.SCORE_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        accounts.currentAccountChanged.connect(self.onCurrentAccountChanged)

        self.adjust_table_by_account()
        self.load()

    def lock(self):
        """
        锁定和网络通信相关的元素
        """
        self.scoreButton.setEnabled(False)
        self.termBox.setEnabled(False)

    def unlock(self):
        """
        解锁和网络通信相关的元素
        """
        self.scoreButton.setEnabled(True)
        self.termBox.setEnabled(True)

    def save(self):
        """
        从当前查询的成绩中保存缓存
        """
        if self.scores is not None:
            cache = AccountDataManager(accounts.current)
            cache.write_json("score.json", {
                "scores": self.scores,
                "terms": [one.text for one in self.termBox.selectedItems()]
            }, allow_overwrite=True)

    def load(self):
        """
        加载缓存的成绩
        """
        if accounts.current is not None:
            cache = AccountDataManager(accounts.current)
            try:
                data = cache.read_json("score.json")
                self.scores = data["scores"]
                terms = data["terms"]
                self.termBox.removeSelectIndexes(list(self.termBox.selected))
                for term in terms:
                    self.termBox.addSelectIndex(self.termBox.findText(term))
                self.onReceiveScore(self.scores, accounts.current.type == accounts.current.POSTGRADUATE, False)
            except (OSError, json.JSONDecodeError, KeyError):
                pass

    def adjust_table_by_account(self):
        """
        根据当前账户类型修改表格样式和成绩查询框样式。
        本科生：课程、学分、绩点、成绩和详情
        研究生：课程、课程类型、学分、绩点和成绩。由于学校系统限制，看不到成绩详情。此外，成绩查询框只能选择“全部学期”
        未登录：按照本科生样式显示
        """
        if accounts.current is None or accounts.current.type == accounts.current.UNDERGRADUATE:
            self.scoreTable.setHorizontalHeaderLabels([self.tr("课程"), self.tr("学分"), self.tr("绩点"), self.tr("成绩"), self.tr("详情")])
            self.scoreTable.verticalHeader().setVisible(False)
            self.scoreTable.setColumnWidth(4, 75)

            self.termBox.clear()
            self.termBox.show_all_select_option = True
            items = []
            term_string = self.guess_term_string()
            for year in range(2016, int(term_string.split('-')[0])):
                for term in range(1, 4):
                    items.append(f"{year}-{year + 1}-{term}")
            for term in range(1, int(term_string.split('-')[2]) + 1):
                items.append(f"{term_string.split('-')[0]}-{term_string.split('-')[1]}-{term}")

            items.reverse()
            self.termBox.addItems(items)
        else:
            self.scoreTable.setHorizontalHeaderLabels([self.tr("课程"), self.tr("课程类型"), self.tr("学分"), self.tr("绩点"), self.tr("成绩")])

            self.termBox.clear()
            self.termBox.show_all_select_option = False
            self.termBox.addItems(["全部学期"])

        if not self.termBox.selected:
            # 生成一个默认的学期
            index = self.termBox.findText(self.guess_last_term_string())
            if index == -1:
                self.termBox.addSelectIndex(0)
            else:
                self.termBox.addSelectIndex(index)

    @staticmethod
    def guess_term_string():
        now = datetime.datetime.now()
        year = now.year
        month = now.month
        if month < 2:
            return f"{year-1}-{year}-1"
        elif month < 7:
            return f"{year-1}-{year}-2"
        elif month < 9:
            return f"{year-1}-{year}-3"
        else:
            return f"{year}-{year+1}-1"

    @staticmethod
    def guess_last_term_string():
        """
        获得一个已经差不多结束的学期的字符串
        """
        now = datetime.datetime.now()
        year = now.year
        month = now.month
        if month < 6:
            return f"{year-1}-{year}-1"
        elif month < 11:
            return f"{year-1}-{year}-2"
        else:
            return f"{year}-{year+1}-1"

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个成功的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.success(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def error(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个错误的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent, isClosable=True)

    def warning(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个警告的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.warning(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.warning(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent,
                                               isClosable=True)

    @pyqtSlot()
    def onScoreButtonClicked(self):
        if self.termBox.allSelected():
            term_number = None
        else:
            term_number = [one.text for one in self.termBox.selectedItems()]
            if not term_number:
                self.warning("", self.tr("请选择至少一个学期"), parent=self)
                return

        self.lock()
        if accounts.current is None:
            self.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self)
            self.unlock()
            return
        # 只有本科生查询成绩可以选学期；研究生没法选，只能查询所有的
        elif accounts.current.type == accounts.current.UNDERGRADUATE:
            self.scoreThread.term_number = term_number
            self.scoreThread.start()
            self.processWidget.setVisible(True)
        else:
            self.graduateScoreThread.start()
            self.graduateProcessWidget.setVisible(True)

    @pyqtSlot(list, bool)
    def onReceiveScore(self, scores: list, is_postgraduate=False, show_success_message=True):
        # 研究生无法区分缓考信息
        if cfg.ignoreLateCourse.value and not is_postgraduate:
            scores = [score for score in scores if "passFlag" not in score or score["passFlag"] or score["specificReason"] != "缓考"]

        self.scores = scores
        self.scoreTable.clearSelection()
        self.scoreTable.setRowCount(len(scores))
        if is_postgraduate:
            for i, score in enumerate(scores):
                self.scoreTable.setItem(i, 0, QTableWidgetItem(score["courseName"]))
                self.scoreTable.setItem(i, 1, QTableWidgetItem(str(score["type"])))
                self.scoreTable.setItem(i, 2, QTableWidgetItem(str(score["coursePoint"])))
                self.scoreTable.setItem(i, 3, QTableWidgetItem(str(score["gpa"])))
                self.scoreTable.setItem(i, 4, QTableWidgetItem(str(score["score"])))
        else:
            # 在更新了“通过成绩单查询成绩绕过评教”功能后，这里可能有两种成绩格式
            # 一种是完整的格式
            # 一种只有 courseName（课程名）, coursePoint（学分）和 score（成绩），其他都没有
            for i, score in enumerate(scores):
                self.scoreTable.setItem(i, 0, QTableWidgetItem(score["courseName"]))
                self.scoreTable.setItem(i, 1, QTableWidgetItem(str(score["coursePoint"])))
                # 如上所述，有的课程没有 gpa（强行从成绩单提取的成绩），因此需要判断
                if score["gpa"]:
                    self.scoreTable.setItem(i, 2, QTableWidgetItem(str(score["gpa"])))
                else:
                    self.scoreTable.setItem(i, 2, QTableWidgetItem(self.tr("无法获得")))
                self.scoreTable.setItem(i, 3, QTableWidgetItem(str(score["score"])))
                self.scoreTable.setItem(i, 4, QTableWidgetItem(""))
                button = TransparentPushButton(self.tr("详情"), self.view)
                # 如果没有 itemList 这个字段，说明没有详情可看，展示一个空的详情对话框并解释原因
                if "itemList" not in score:
                    button.clicked.connect(lambda _: self.showEmptyDetailDialog())
                else:
                    button.clicked.connect(lambda _, s=score: self.showDetailDialog(s))
                self.scoreTable.setCellWidget(i, 4, button)
                self.scoreTable.item(i, 4).setFlags(Qt.ItemIsEditable)

        self.onSelectScore()
        self.save()
        if show_success_message:
            self.success("", self.tr("查询成功"), parent=self)

    def showDetailDialog(self, score):
        dialog = ScoreDetailDialog(score, parent=self)
        dialog.exec()

    def showEmptyDetailDialog(self):
        dialog = EmptyScoreDetailDialog(parent=self)
        dialog.exec()

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        self.scoreTable.clearContents()
        self.scoreTable.setRowCount(7)
        self.statisticTable.clearContents()
        self.adjust_table_by_account()
        self.load()

    @pyqtSlot()
    def onSelectScore(self):
        if not self.scores:
            # 如果没有成绩，则清空统计表后返回
            self.statisticTable.setItem(0, 0, QTableWidgetItem(""))
            self.statisticTable.setItem(0, 1, QTableWidgetItem(""))
            self.statisticTable.setItem(0, 2, QTableWidgetItem(""))
            return

        selected_rows = [index.row() for index in self.scoreTable.selectionModel().selectedRows()]

        if not selected_rows:
            selected_rows = list(range(self.scoreTable.rowCount()))

        try:
            scores = [self.scores[index] for index in selected_rows]
        except IndexError:
            return

        credits_ = [score["coursePoint"] for score in scores]
        total_credit = sum(credits_)
        # 0 学分课程无法计算绩点和平均分，直接返回
        if total_credit == 0:
            return
        gpa_sum_list = []
        # 有的课程没有 gpa（强行从成绩单提取的成绩），因此需要判断
        # 我们忽略这些没有 gpa 的课程
        # 没有 gpa 的课程都是实验课程（成绩单只有 A/A+ 这样的符号）
        # 我们为它们的均分计算也做适配
        score_sum_list = []
        inaccurate_warning = False
        inaccurate_count = 0
        for score in scores:
            if score["gpa"] is not None:
                gpa_sum_list.append(score["gpa"] * score["coursePoint"])
            else:
                inaccurate_warning = True
                inaccurate_count += 1
                continue
            # 忽略成绩不是数字的课程
            if isinstance(score["score"], int) or isinstance(score["score"], float):
                score_sum_list.append(score["score"] * score["coursePoint"])
            else:
                inaccurate_warning = True
                inaccurate_count += 1
                continue

        gpa = sum(gpa_sum_list) / (total_credit - inaccurate_count)
        average = sum(score_sum_list) / (total_credit - inaccurate_count)

        self.statisticTable.setItem(0, 0, QTableWidgetItem(str(total_credit)))
        # 如果存在无法计算均分/gpa 的课程，则提示不精确
        if not inaccurate_warning:
            self.statisticTable.setItem(0, 1, QTableWidgetItem(str(round(gpa, 3))))
            self.statisticTable.setItem(0, 2, QTableWidgetItem(str(round(average, 3))))
        else:
            self.statisticTable.setItem(0, 1, QTableWidgetItem(f"{round(gpa, 3)}（不精确）"))
            self.statisticTable.setItem(0, 2, QTableWidgetItem(f"{round(average, 3)}（不精确）"))
