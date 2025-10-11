from typing import List, Dict

from PyQt5.QtCore import Qt, pyqtSlot, QObject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import ScrollArea, SubtitleLabel, CaptionLabel, ComboBox, PlainTextEdit, PushButton, BodyLabel, \
    MessageBoxBase

from app.utils import accounts, AccountDataManager
from gste.judge import GraduateQuestionnaireData, GraduateQuestionItem, GraduateQuestionnaire


class _CollapsibleTextSection(QWidget):
    """
    简易可折叠文本输入区：标题栏 + PlainTextEdit
    - 默认第一项展开，其他为折叠状态
    - UI 组件，不包含业务逻辑
    """
    def __init__(self, title: str, placeholder: str = "", *, expanded: bool = False, max_width: int | None = None, parent=None):
        super().__init__(parent)
        self._expanded = expanded

        self.vBox = QVBoxLayout(self)
        self.vBox.setContentsMargins(0, 0, 0, 0)
        self.vBox.setSpacing(6)

        # 头部：标题 + 展开/收起按钮
        self.header = QWidget(self)
        self.headerLayout = QHBoxLayout(self.header)
        self.headerLayout.setContentsMargins(0, 0, 0, 0)
        self.headerLayout.setSpacing(8)

        self.titleLabel = BodyLabel(title, self)
        self.titleLabel.setMaximumWidth(max_width)
        # 长标题自动换行，避免拉伸对话框
        try:
            self.titleLabel.setWordWrap(True)
        except Exception:
            pass
        self.toggleBtn = PushButton(self._buttonText(), self)
        self.toggleBtn.setFixedWidth(76)
        self.toggleBtn.clicked.connect(self._onToggleClicked)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.toggleBtn, alignment=Qt.AlignRight)

        # 内容：多行文本
        self.editor = PlainTextEdit(self)
        self.editor.setPlaceholderText(placeholder)
        self.editor.setVisible(self._expanded)

        # 限制区域最大宽度，避免过宽
        if isinstance(max_width, int) and max_width > 0:
            self.setMaximumWidth(max_width)
            self.editor.setMaximumWidth(max_width)

        self.vBox.addWidget(self.header)
        self.vBox.addWidget(self.editor)

    def _buttonText(self) -> str:
        return self.tr("收起") if self._expanded else self.tr("展开")

    @pyqtSlot()
    def _onToggleClicked(self):
        self._expanded = not self._expanded
        self.editor.setVisible(self._expanded)
        self.toggleBtn.setText(self._buttonText())

    def setText(self, text: str):
        self.editor.setPlainText(text or "")

    def text(self) -> str:
        return self.editor.toPlainText()


class GraduateJudgeCacheManager(QObject):
    """
    利用 CacheManager 类，将所有评教缓存信息统一存储到一个文件中
    """
    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
            cls.__instance.__init__()
            cls.__instance.caches = {}
            try:
                cls.__instance.load()
            except Exception:
                pass
            accounts.currentAccountChanged.connect(cls.__instance.onCurrentAccountChanged, Qt.UniqueConnection)

        return cls.__instance

    def add(self, uuid: str, score: int, comment_diction: Dict):
        """
        添加一条新的缓存信息。
        :param uuid: 唯一存储 ID
        :param score: 评价等级，分为 3-0 ，对应“优”，“良”，“合格”，“不合格"
        :param comment_diction: 各个文本题目的评论，字典形式存储。格式应当为题目名称/ID->内容
        :raises ValueError: score 不符合要求时抛出
        """
        if not 0 <= score <= 3:
            raise ValueError("score 必须为 '优', '良', '合格', '不合格' 之一")
        self.caches[uuid] = {
            "score": score,
            "comment": comment_diction
        }

    def delete(self, uuid: str):
        self.caches.pop(uuid)

    def get(self, uuid: str) -> Dict:
        data = self.caches.get(uuid)
        if not isinstance(data, dict):
            return {}
        data["score"] = data.get("score", 3)
        return data

    def clear(self):
        self.caches.clear()

    def save(self):
        """
        写入缓存到当前账户的缓存文件中
        """
        cache = AccountDataManager(accounts.current)
        cache.write_json("judge_cache.json", self.caches, True)

    def load(self):
        """
        从当前账户的缓存文件中读取缓存
        """
        cache = AccountDataManager(accounts.current)
        self.caches = cache.read_json("judge_cache.json")

    @pyqtSlot()
    def onCurrentAccountChanged(self):
        try:
            self.load()
        except Exception:
            pass


class GraduateJudgeOptionInterface(ScrollArea):
    """
    研究生评教 UI：
    - 顶部等级选择：优 / 良 / 合格 / 不合格
    - 根据问卷中的 textarea 数量生成对应的可折叠输入区
    - 仅包含 UI，不包含具体提交/网络逻辑
    """
    def __init__(self, questionnaire_title: str, qdata: GraduateQuestionnaireData, parent=None):
        super().__init__(parent=parent)
        self.qdata = qdata
        # 控制文本域最大宽度，避免对话框被长问题拉宽
        self._maxSectionWidth = 850
        # 缓存 key：使用传入的标题，避免将控件对象作为键
        self._cacheKey = str(questionnaire_title)

        # 主容器
        self.view = QWidget(self)
        self.view.setObjectName("GraduateJudgeOptionView")
        self.vBox = QVBoxLayout(self.view)
        self.vBox.setContentsMargins(16, 12, 16, 12)
        self.vBox.setSpacing(12)

        self.cache_manager = GraduateJudgeCacheManager()

        # 标题与说明
        self.title = SubtitleLabel(questionnaire_title, self)
        self.desc = CaptionLabel(self.tr("请先选择总体等级，然后根据需要填写意见建议。"), self)
        self.desc.setTextColor("#606060", "#d2d2d2")

        # 等级选择
        self.levelBox = ComboBox(self.view)
        self.texts = (self.tr("优秀"), self.tr("良好"), self.tr("合格"), self.tr("不合格"))
        for text in self.texts:
            self.levelBox.addItem(text)
        self.levelBox.setCurrentIndex(0)

        levelRow = QWidget(self.view)
        levelLayout = QHBoxLayout(levelRow)
        levelLayout.setContentsMargins(0, 0, 0, 0)
        levelLayout.setSpacing(8)

        levelLayout.addWidget(BodyLabel(self.tr("总体等级"), self))
        levelLayout.addStretch(1)
        levelLayout.addWidget(self.levelBox)
        # 居中对齐，防止行控件也撑宽
        _policy = QSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        levelRow.setSizePolicy(_policy)
        levelRow.setMaximumWidth(self._maxSectionWidth)
        # 注意：不在这里添加到布局，统一在“组装布局”处添加并设置对齐方式

        # 文本区：根据 textarea 题目生成
        self.sections: List[_CollapsibleTextSection] = []
        self.sectionById: Dict[str, _CollapsibleTextSection] = {}

        text_questions = [q for q in (self.qdata.questions or []) if q.view == 'textarea']
        # 若没有 textarea，也保留一个默认的意见区
        if not text_questions:
            text_questions = [GraduateQuestionItem(id="__default__", name=self.tr("意见与建议"), view="textarea")]

        for i, q in enumerate(text_questions):
            expanded = (i == 0)
            placeholder = self.tr("可以留空：{}").format(q.name)
            section = _CollapsibleTextSection(q.name, placeholder=placeholder, expanded=expanded, max_width=self._maxSectionWidth, parent=self.view)
            self.sections.append(section)
            self.sectionById[q.id] = section

        # 组装布局
        self.vBox.addWidget(self.title, alignment=Qt.AlignHCenter)
        self.vBox.addWidget(self.desc, alignment=Qt.AlignHCenter)
        self.vBox.addWidget(levelRow, alignment=Qt.AlignHCenter)
        for sec in self.sections:
            self.vBox.addWidget(sec, 0, Qt.AlignHCenter)
        self.vBox.addStretch(1)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

        # 设置空白背景
        self.setObjectName("GraduateJudgeOptionInterface")
        self.view.setObjectName("view")
        self.setStyleSheet("""
        GraduateJudgeOptionInterface, #view{
            background-color: transparent;
        }
        QScrollArea {
            border: none;
            background-color: transparent;
        }
        """)

        self.load()

    def save(self):
        self.cache_manager.add(self._cacheKey, 3 - self.texts.index(self.currentLevelText()), self.textsByQuestionId())
        self.cache_manager.save()

    def load(self):
        """
        从缓存中读取当前评教信息
        """
        data = self.cache_manager.get(self._cacheKey)
        if data:
            self.levelBox.setCurrentIndex(3 - data.get("score", 3))
            for qid, text in data.get("comment", {}).items():
                if qid in self.sectionById:
                    self.sectionById[qid].setText(text)

    # 下面两个 getter 仅用于外部读取 UI 状态（如果需要）。UI 本身不负责网络/提交逻辑。
    def currentLevelText(self) -> str:
        return self.levelBox.currentText()

    def currentLevel(self) -> int:
        """
        获得当前问卷的评分（优：3，良：2，合格：1，不合格：0）
        该评分与问卷中的评分对应
        """
        return 3 - self.levelBox.currentIndex()

    def textsByQuestionId(self) -> Dict[str, str]:
        return {qid: sec.text() for qid, sec in self.sectionById.items()}


class GraduateJudgeOptionMessageBox(MessageBoxBase):
    """
    将评教选择界面封装为对话框，用于显示评教选项。
    """
    def __init__(self, title: str, data: GraduateQuestionnaireData, parent=None):
        super().__init__(parent)

        self.interface = GraduateJudgeOptionInterface(title, data, self)
        self.viewLayout.addWidget(self.interface, 1)

        self.yesButton.setText(self.tr("提交"))
        self.cancelButton.setText(self.tr("保存但不提交"))

        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self.onSaveButtonClicked)
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self.onYesButtonClicked)

    @pyqtSlot()
    def onSaveButtonClicked(self):
        self.interface.save()
        self.reject()

    @pyqtSlot()
    def onYesButtonClicked(self):
        self.interface.save()
        self.accept()
