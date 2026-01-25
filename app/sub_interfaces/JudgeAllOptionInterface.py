from PyQt5.QtCore import pyqtSlot, Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, MessageBoxBase, SubtitleLabel, ToolTipFilter, ComboBox, ToolTipPosition, \
    PlainTextEdit, CaptionLabel

from app.threads.ProcessWidget import ProcessThread
from app.utils import StyleSheet, accounts
from jwxt import QuestionnaireTemplate


class JudgeAllOptionInterface(ScrollArea):
    """
    全部评教选项界面，可以在此界面选择评教评分、填写自定义评语等。
    """
    submitButtonClicked = pyqtSignal()

    def __init__(self, thread_: ProcessThread, parent=None):
        super().__init__(parent=parent)
        self.thread_ = thread_

        self.setObjectName("JudgeAllOptionInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.title = SubtitleLabel("全部评教", self)
        self.detailLabel = CaptionLabel("一键评教所有未评教课程", self)
        self.detailLabel.setTextColor("#606060", "#d2d2d2")

        # 课程类型框和分数框部分
        self.scoreBox = ComboBox(self.view)
        self.textArea = PlainTextEdit(self.view)

        # 设置工具提示
        self.scoreBox.setToolTip(self.tr("选择预先设置的问卷分数"))
        self.scoreBox.setToolTipDuration(1000)
        self.scoreBox.installEventFilter(ToolTipFilter(self.scoreBox, showDelay=300, position=ToolTipPosition.TOP))

        # 设置分数的可选选项
        if accounts.current.type is not None and accounts.current.type == accounts.current.POSTGRADUATE:
            self.scoreBox.addItem(self.tr("优"), userData=3)
            self.scoreBox.addItem(self.tr("良"), userData=2)
            self.scoreBox.addItem(self.tr("合格"), userData=1)
            self.scoreBox.addItem(self.tr("不合格"), userData=0)

            self.textArea.setPlaceholderText(self.tr("（可以留空）请写下对课程的评价。\n所有主观题目均会被设置为此答案，如果想更详细的填写问卷，请逐张填写。"))
        else:
            score_dict = {QuestionnaireTemplate.Score.HUNDRED: "100分",
                          QuestionnaireTemplate.Score.EIGHTY: "80分",
                          QuestionnaireTemplate.Score.SIXTY: "60分",
                          QuestionnaireTemplate.Score.FORTY: "40分"}
            for one in QuestionnaireTemplate.Score:
                self.scoreBox.addItem(self.tr(score_dict[one]), userData=one)

            self.textArea.setPlaceholderText(self.tr("（可以留空）请写下老师教学方面的优点或有待改进的地方，以及对所使用教材的意见"))


        self.vBoxLayout.addWidget(self.title, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.detailLabel, alignment=Qt.AlignHCenter)
        self.vBoxLayout.addWidget(self.scoreBox)
        self.vBoxLayout.addWidget(self.textArea, stretch=1)

        self.textArea.setFocus()

        StyleSheet.JUDGE_OPTION_INTERFACE.apply(self)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

    @pyqtSlot()
    def onSubmitButtonClicked(self):
        self.submitButtonClicked.emit()

    def getText(self):
        return self.textArea.toPlainText() or "无"

    def getScore(self):
        return self.scoreBox.currentData()


class JudgeAllOptionMessageBox(MessageBoxBase):
    """
    将评教选择界面封装为对话框，用于显示评教选项。
    """
    def __init__(self, thread_: ProcessThread, parent=None):
        super().__init__(parent)

        self.interface = JudgeAllOptionInterface(thread_, self)
        self.viewLayout.addWidget(self.interface, 1)

        self.yesButton.setText(self.tr("开始"))
        self.cancelButton.setText(self.tr("取消"))

        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self.onYesButtonClicked)

    def getText(self):
        return self.interface.getText()

    def getScore(self):
        return self.interface.getScore()

    @pyqtSlot()
    def onCancelButtonClicked(self):
        self.reject()

    @pyqtSlot()
    def onYesButtonClicked(self):
        self.interface.onSubmitButtonClicked()
        self.accept()
