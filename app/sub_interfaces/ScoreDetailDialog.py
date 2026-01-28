from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem, QHeaderView
from qfluentwidgets import MessageBoxBase, TableWidget, BodyLabel, SubtitleLabel
from typing import Dict


class ScoreDetailDialog(MessageBoxBase):
    """
    展示成绩详情的对话框
    """
    def __init__(self, score: Dict, parent=None):
        """
        初始化对话框
        :param score: 一个字典，包含了成绩的详细信息
        :param parent: 父窗口
        """
        super().__init__(parent)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.score = score

        self.titleLabel = SubtitleLabel(score["courseName"], self)

        self.header = BodyLabel(self.tr("课程成绩"), self)
        self.scoreLabel = SubtitleLabel(str(round(score["score"], 3)), self)

        self.detailTable = TableWidget(self)
        self.detailTable.setColumnCount(3)
        self.detailTable.setHorizontalHeaderLabels([self.tr("项目"), self.tr("百分比"), self.tr("成绩")])
        self.detailTable.setRowCount(len(score["itemList"]))
        self.detailTable.setEditTriggers(self.detailTable.NoEditTriggers)
        self.detailTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.detailTable.verticalHeader().setVisible(False)

        for i, item in enumerate(score["itemList"]):
            self.detailTable.setItem(i, 0, QTableWidgetItem(item["itemName"]))
            self.detailTable.setItem(i, 1, QTableWidgetItem(f"{int(item['itemPercent'] * 100)}%" if item['itemPercent'] != 0 else self.tr("未知")))
            self.detailTable.setItem(i, 2, QTableWidgetItem(str(round(item["itemScore"], 3))))

        self.detailTable.resizeColumnsToContents()

        self.viewLayout.addWidget(self.titleLabel, 0, alignment=Qt.AlignHCenter)
        self.viewLayout.addStretch(1)
        self.viewLayout.addWidget(self.header, 0, alignment=Qt.AlignHCenter)
        self.viewLayout.addWidget(self.scoreLabel, 0, alignment=Qt.AlignHCenter)
        self.viewLayout.addStretch(1)
        self.viewLayout.addWidget(self.detailTable, 5, alignment=Qt.AlignHCenter)


class EmptyScoreDetailDialog(MessageBoxBase):
    """
    展示无成绩详情的对话框
    """
    def __init__(self, parent=None):
        """
        初始化对话框
        :param parent: 父窗口
        """
        super().__init__(parent)

        self.buttonGroup.setVisible(False)
        self.setClosableOnMaskClicked(True)

        self.titleLabel = SubtitleLabel(self.tr("无成绩详情"), self)

        self.messageLabel = BodyLabel(self.tr("该课程的成绩是绕过评教，直接从成绩单获得的，因此暂无成绩详情信息。"), self)

        self.viewLayout.addWidget(self.titleLabel, 0, alignment=Qt.AlignHCenter)
        self.viewLayout.addStretch(1)
        self.viewLayout.addWidget(self.messageLabel, 0, alignment=Qt.AlignHCenter)
        self.viewLayout.addStretch(1)
