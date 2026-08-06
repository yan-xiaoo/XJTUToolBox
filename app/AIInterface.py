from __future__ import annotations

import html
import threading
import time
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from PyQt5 import sip
from PyQt5.QtCore import QEasingCurve, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    HeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PopUpAniStackedWidget,
    PasswordLineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    TextBrowser,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
    isDarkTheme,
    qconfig,
)

from ai_assistant import (
    AIClient,
    AIConfigStore,
    AIProfile,
    ChatMessage,
    PRESETS,
    ProviderConfig,
    SecretPersistence,
    CAPABILITIES,
    ConversationStore,
    ModelCatalogClient,
    ModelOperationCancelled,
    SEARCH_ENGINES,
    SearchHumanVerificationRequired,
    WebSearchClient,
    collect_local_context,
)
from ai_assistant.markdown_render import render_markdown_fragment
from ai_assistant.web_search import format_search_context


@dataclass(frozen=True)
class _AIRequestOutcome:
    result: object
    search_count: int
    session_id: str = ""


@dataclass(frozen=True)
class _AIRequestFailure:
    message: str
    session_id: str = ""


class _AIRequestThread(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    webSearchDisabled = pyqtSignal(object)
    cancelled = pyqtSignal()
    stageChanged = pyqtSignal(str)

    def __init__(
        self,
        messages,
        config,
        *,
        search_query="",
        search_settings=None,
        local_context="",
        session_id="",
        parent=None,
    ):
        super().__init__(parent)
        self.messages = list(messages)
        self.config = config
        self.search_query = search_query
        self.search_settings = search_settings
        self.local_context = local_context
        self.session_id = session_id
        self.cancel_event = threading.Event()
        self.ai_client = AIClient(timeout=(15, 120))
        self.search_client = WebSearchClient(timeout=(10, 20))

    def cancel(self) -> None:
        self.cancel_event.set()
        self.ai_client.session.close()
        self.search_client.session.close()

    def run(self):
        try:
            messages = list(self.messages)
            context_messages = []
            if self.local_context:
                context_messages.append(ChatMessage("system", self.local_context))
            search_count = 0
            if self.search_settings is not None:
                self.stageChanged.emit("searching")
                results = self.search_client.search(
                    self.search_query,
                    **self.search_settings,
                )
                search_count = len(results)
                context_messages.append(ChatMessage("system", format_search_context(results)))
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
            self.stageChanged.emit("thinking")
            insertion = 1 if messages and messages[0].role == "system" else 0
            messages[insertion:insertion] = context_messages
            result = self.ai_client.complete(messages, self.config)
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
        except SearchHumanVerificationRequired as error:
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.webSearchDisabled.emit(_AIRequestFailure(str(error), self.session_id))
        except Exception as error:
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(_AIRequestFailure(str(error) or type(error).__name__, self.session_id))
        else:
            self.succeeded.emit(_AIRequestOutcome(result, search_count, self.session_id))


class _ModelListThread(QThread):
    succeeded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.client = ModelCatalogClient(timeout=(10, 20))

    def cancel(self) -> None:
        self.client.session.close()

    def run(self):
        try:
            models = self.client.list_models(self.config)
        except Exception as error:
            self.failed.emit(str(error) or type(error).__name__)
        else:
            self.succeeded.emit(models)


class _ModelPullThread(QThread):
    progressed = pyqtSignal(object)
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, config, model, parent=None):
        super().__init__(parent)
        self.config = config
        self.model = model
        self.cancel_event = threading.Event()
        self.client = ModelCatalogClient(timeout=(10, 15))

    def cancel(self) -> None:
        self.cancel_event.set()
        self.client.session.close()

    def run(self):
        try:
            self.client.pull_ollama_model(
                self.config,
                self.model,
                progress=self.progressed.emit,
                cancel_event=self.cancel_event,
            )
        except ModelOperationCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error) or type(error).__name__)
        else:
            self.succeeded.emit()


class AIInterface(QFrame):
    """Provider-neutral Fluent chat interface named Wenzhou (问舟)."""

    PROTOCOLS = (
        ("openai", "OpenAI-compatible"),
        ("anthropic", "Anthropic Messages"),
        ("gemini", "Gemini generateContent"),
        ("ollama", "Ollama Chat"),
    )
    STUCK_SECONDS = 30

    def __init__(
        self,
        parent=None,
        config_store: AIConfigStore | None = None,
        conversation_store: ConversationStore | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("AIInterface")
        self.store = config_store or AIConfigStore()
        self.profile = self.store.load_profiles()[0]
        self._lastSearxngEndpoint = (
            self.profile.search_endpoint if self.profile.search_engine != "duckduckgo" else ""
        )
        self.conversationStore = conversation_store or ConversationStore(
            self.store.path.with_name("ai_conversations.json")
        )
        self.conversationState = self.conversationStore.load()
        self.messages: list[ChatMessage] = self.conversationState.active.messages
        self.assistantMeta: list[dict[str, object]] = self.conversationState.active.assistant_meta
        self.requestThread: _AIRequestThread | None = None
        self.modelListThread: _ModelListThread | None = None
        self.modelPullThread: _ModelPullThread | None = None
        self._requestState = "idle"
        self._requestError = ""
        self._requestStarted = 0.0
        self._requestElapsed = 0.0
        self._lastTickSecond = -1
        self._requestSessionId = ""
        self._loadingProfile = False
        self._switchingSession = False

        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.pageStack = PopUpAniStackedWidget(self)
        self.compactPage = QWidget(self.pageStack)
        self.compactPage.setObjectName("wenzhouCompactPage")
        self.mainLayout = QVBoxLayout(self.compactPage)
        self.mainLayout.setContentsMargins(24, 18, 24, 18)
        self.mainLayout.setSpacing(9)
        titleLayout = QHBoxLayout()
        titleLayout.addWidget(TitleLabel(self.tr("问舟"), self.compactPage))
        self.sessionCombo = ComboBox(self.compactPage)
        self.sessionCombo.setMinimumWidth(150)
        self.sessionCombo.setMaximumWidth(240)
        self.sessionCombo.setToolTip(self.tr("切换本地对话"))
        titleLayout.addWidget(self.sessionCombo)
        self.newConversationButton = TransparentToolButton(FluentIcon.ADD, self.compactPage)
        self.newConversationButton.setToolTip(self.tr("新建对话"))
        titleLayout.addWidget(self.newConversationButton)
        self.expandConversationButton = TransparentToolButton(FluentIcon.FULL_SCREEN, self.compactPage)
        self.expandConversationButton.setToolTip(self.tr("展开为独立对话页"))
        titleLayout.addWidget(self.expandConversationButton)
        titleLayout.addStretch(1)
        self.statusLabel = CaptionLabel(self.tr("就绪 · 数据能力默认关闭"), self.compactPage)
        self.statusLabel.setMaximumWidth(300)
        titleLayout.addWidget(self.statusLabel, alignment=Qt.AlignBottom)
        self.mainLayout.addLayout(titleLayout)

        self._createConfigCard()
        self._createCapabilityCard()
        self._createSettingsTabs()
        self._createChatCard()
        self._createInputArea()
        self._createExpandedConversationPage()

        self.pageStack.addWidget(self.compactPage, deltaY=28)
        self.pageStack.addWidget(self.expandedPage, deltaY=28)
        self.pageStack.setCurrentWidget(self.compactPage)
        self.rootLayout.addWidget(self.pageStack)

        self.requestTimer = QTimer(self)
        self.requestTimer.setInterval(250)
        self.requestTimer.timeout.connect(self._onRequestTick)
        self._refreshSessionControls()
        self._loadProfileIntoForm()
        if self.store.last_error:
            self.storageLabel.setText(self.tr("原 AI 配置损坏，已安全回退为默认配置"))
        if self.conversationStore.last_error:
            self.statusLabel.setText(self.tr("对话历史损坏，已安全回退为新对话"))
        self.sessionCombo.currentIndexChanged.connect(self._onSessionComboChanged)
        self.expandedSessionList.currentRowChanged.connect(self._onExpandedSessionChanged)
        self.newConversationButton.clicked.connect(self.createConversation)
        self.expandConversationButton.clicked.connect(self.showExpandedConversation)
        qconfig.themeChanged.connect(self._onThemeChanged)
        QTimer.singleShot(0, self._refreshSettingsHeight)
        self._applyThemeSurfaces()
        self._renderTranscript()

    def _createConfigCard(self) -> None:
        self.configCard = HeaderCardWidget(self)
        self.configCard.setTitle(self.tr("模型服务 · 提供商用于快速配置，协议可独立选择"))
        widget = QWidget(self.configCard)
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(9)
        layout.setVerticalSpacing(7)

        self.presetCombo = ComboBox(widget)
        self.presetCombo.addItems([preset.name for preset in PRESETS])
        self.presetCombo.setCurrentIndex(max(0, next(
            (index for index, preset in enumerate(PRESETS) if preset.id == self.profile.preset_id), 0
        )))
        self.protocolCombo = ComboBox(widget)
        self.protocolCombo.addItems([label for _, label in self.PROTOCOLS])
        self.baseUrlEdit = LineEdit(widget)
        self.baseUrlEdit.setPlaceholderText("https://api.example.com/v1")
        self.modelCombo = EditableComboBox(widget)
        self.modelCombo.setPlaceholderText(self.tr("输入或从列表选择模型 ID"))
        self.refreshModelsButton = PushButton(FluentIcon.SYNC, self.tr("刷新列表"), widget)
        self.downloadModelButton = PushButton(FluentIcon.DOWNLOAD, self.tr("下载模型"), widget)
        self.apiKeyEdit = PasswordLineEdit(widget)
        self.apiKeyEdit.setPlaceholderText(self.tr("API Key（不写入配置文件；Ollama 本地可留空）"))
        self.saveButton = PushButton(FluentIcon.SAVE, self.tr("保存配置"), widget)
        self.modelProgress = ProgressBar(widget)
        self.modelProgress.setRange(0, 100)
        self.modelProgress.setVisible(False)
        self.modelStatusLabel = CaptionLabel(widget)
        self.storageLabel = self.modelStatusLabel

        layout.addWidget(BodyLabel(self.tr("提供商"), widget), 0, 0)
        layout.addWidget(self.presetCombo, 0, 1)
        layout.addWidget(BodyLabel(self.tr("协议"), widget), 0, 2)
        layout.addWidget(self.protocolCombo, 0, 3)
        layout.addWidget(BodyLabel("Base URL", widget), 1, 0)
        layout.addWidget(self.baseUrlEdit, 1, 1, 1, 3)
        layout.addWidget(BodyLabel(self.tr("模型"), widget), 2, 0)
        layout.addWidget(self.modelCombo, 2, 1)
        layout.addWidget(self.refreshModelsButton, 2, 2)
        layout.addWidget(self.downloadModelButton, 2, 3)
        layout.addWidget(BodyLabel("API Key", widget), 3, 0)
        layout.addWidget(self.apiKeyEdit, 3, 1, 1, 2)
        layout.addWidget(self.saveButton, 3, 3)
        layout.addWidget(self.modelProgress, 4, 0, 1, 2)
        layout.addWidget(self.modelStatusLabel, 4, 2, 1, 2)
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(3, 2)
        self.configCard.viewLayout.addWidget(widget)

        self.presetCombo.currentIndexChanged.connect(self._onPresetChanged)
        self.protocolCombo.currentIndexChanged.connect(self._onProtocolChanged)
        self.refreshModelsButton.clicked.connect(self.refreshModels)
        self.downloadModelButton.clicked.connect(self._onDownloadModelClicked)
        self.saveButton.clicked.connect(self.saveConfiguration)

    def _createCapabilityCard(self) -> None:
        self.capabilityCard = HeaderCardWidget(self)
        self.capabilityCard.setTitle(self.tr("能力开关 · 只有勾选的数据才会进入当前模型请求"))
        widget = QWidget(self.capabilityCard)
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        self.capabilityChecks = {}
        for index, capability in enumerate(CAPABILITIES):
            checkbox = CheckBox(capability.name, widget)
            checkbox.setToolTip(capability.description + ("；属于个人数据" if capability.sensitive else ""))
            self.capabilityChecks[capability.id] = checkbox
            layout.addWidget(checkbox, index // 3, index % 3)

        row = 2
        self.searchEngineCombo = ComboBox(widget)
        self.searchEngineCombo.addItems([name for _, name in SEARCH_ENGINES])
        self.searchEndpointEdit = LineEdit(widget)
        self.searchEndpointEdit.setPlaceholderText("https://search.example/search")
        self.searchLimitCombo = ComboBox(widget)
        self.searchLimitCombo.addItems(["3", "5", "8", "10"])
        self.capabilityStatusLabel = CaptionLabel(
            self.tr("全部默认关闭；课表、成绩、考勤只读取本机缓存，不读取账户凭据。"), widget
        )
        self.capabilityStatusLabel.setWordWrap(True)
        layout.addWidget(BodyLabel(self.tr("搜索引擎"), widget), row, 0)
        layout.addWidget(self.searchEngineCombo, row, 1)
        layout.addWidget(self.searchEndpointEdit, row, 2)
        layout.addWidget(BodyLabel(self.tr("结果数"), widget), row, 3)
        layout.addWidget(self.searchLimitCombo, row, 4)
        layout.addWidget(self.capabilityStatusLabel, row + 1, 0, 1, 5)
        layout.setColumnStretch(2, 2)
        self.capabilityCard.viewLayout.addWidget(widget)
        self.searchEngineCombo.currentIndexChanged.connect(self._onSearchEngineChanged)
        self.capabilityChecks["web_search"].toggled.connect(self._updateSearchControls)
        for checkbox in self.capabilityChecks.values():
            checkbox.toggled.connect(self._persistCapabilityPreferences)
        self.searchEndpointEdit.editingFinished.connect(self._persistSearchPreferences)
        self.searchLimitCombo.currentTextChanged.connect(self._persistSearchPreferences)

    def _createSettingsTabs(self) -> None:
        self.settingsPivot = SegmentedWidget(self)
        self.settingsStack = QStackedWidget(self)
        self.settingsStack.addWidget(self.configCard)
        self.settingsStack.addWidget(self.capabilityCard)
        self.settingsStack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.settingsPivot.addItem(
            routeKey="model-service",
            text=self.tr("模型配置"),
            onClick=lambda: self._showSettingsCard(self.configCard),
        )
        self.settingsPivot.addItem(
            routeKey="capabilities",
            text=self.tr("能力开关"),
            onClick=lambda: self._showSettingsCard(self.capabilityCard),
        )
        self.settingsPivot.setCurrentItem("model-service")
        self.settingsStack.setCurrentWidget(self.configCard)
        self.mainLayout.addWidget(self.settingsPivot, alignment=Qt.AlignLeft)
        self.mainLayout.addWidget(self.settingsStack)

    def _showSettingsCard(self, card: QWidget) -> None:
        self.settingsStack.setCurrentWidget(card)
        self._refreshSettingsHeight()

    @pyqtSlot()
    def _refreshSettingsHeight(self) -> None:
        # HeaderCardWidget's 48 px header and 24 px content margins are part of
        # its natural size.  Never compress form rows below their size hints.
        required = max(
            self.configCard.sizeHint().height(),
            self.capabilityCard.sizeHint().height(),
        )
        self.settingsStack.setMinimumHeight(required)

    def _createChatCard(self) -> None:
        self.chatCard = HeaderCardWidget(self)
        self.chatCard.setTitle(self.tr("对话 · Markdown 安全渲染"))
        self.transcript = TextBrowser(self.chatCard)
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self._openSafeLink)
        self.transcript.setMinimumHeight(80)
        self.chatCard.viewLayout.addWidget(self.transcript)
        self.mainLayout.addWidget(self.chatCard, stretch=1)

    def _createInputArea(self) -> None:
        layout = QHBoxLayout()
        self.inputEdit = TextEdit(self)
        self.inputEdit.setPlaceholderText(self.tr("输入消息…"))
        self.inputEdit.setMaximumHeight(65)
        buttons = QVBoxLayout()
        self.sendButton = PrimaryPushButton(FluentIcon.SEND, self.tr("发送"), self)
        self.cancelButton = PushButton(FluentIcon.CANCEL, self.tr("取消"), self)
        self.cancelButton.setVisible(False)
        self.clearButton = PushButton(FluentIcon.DELETE, self.tr("新对话"), self)
        buttons.addWidget(self.sendButton)
        buttons.addWidget(self.cancelButton)
        buttons.addWidget(self.clearButton)
        buttons.addStretch(1)
        layout.addWidget(self.inputEdit, stretch=1)
        layout.addLayout(buttons)
        self.mainLayout.addLayout(layout)
        self.sendButton.clicked.connect(self.sendMessage)
        self.cancelButton.clicked.connect(self.cancelRequest)
        self.clearButton.clicked.connect(self.createConversation)

    def _createExpandedConversationPage(self) -> None:
        self.expandedPage = QWidget(self.pageStack)
        self.expandedPage.setObjectName("wenzhouExpandedConversationPage")
        page_layout = QVBoxLayout(self.expandedPage)
        page_layout.setContentsMargins(24, 18, 24, 18)
        page_layout.setSpacing(10)

        toolbar = QHBoxLayout()
        self.collapseConversationButton = TransparentToolButton(
            FluentIcon.BACK_TO_WINDOW, self.expandedPage
        )
        self.collapseConversationButton.setToolTip(self.tr("返回合并页面"))
        toolbar.addWidget(self.collapseConversationButton)
        toolbar.addWidget(TitleLabel(self.tr("问舟 · 对话"), self.expandedPage))
        toolbar.addStretch(1)
        self.expandedStatusLabel = CaptionLabel(self.tr("就绪"), self.expandedPage)
        self.expandedStatusLabel.setMaximumWidth(300)
        toolbar.addWidget(self.expandedStatusLabel, alignment=Qt.AlignBottom)
        page_layout.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(12)
        session_panel = QWidget(self.expandedPage)
        session_panel.setObjectName("wenzhouSessionPanel")
        session_panel.setMinimumWidth(170)
        session_panel.setMaximumWidth(240)
        session_layout = QVBoxLayout(session_panel)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(7)
        session_layout.addWidget(BodyLabel(self.tr("本地对话"), session_panel))
        self.expandedSessionList = ListWidget(session_panel)
        self.expandedSessionList.setMinimumWidth(0)
        session_layout.addWidget(self.expandedSessionList, stretch=1)
        self.expandedNewButton = PushButton(FluentIcon.ADD, self.tr("新建"), session_panel)
        self.expandedRenameButton = PushButton(FluentIcon.EDIT, self.tr("重命名"), session_panel)
        self.expandedDeleteButton = PushButton(FluentIcon.DELETE, self.tr("删除"), session_panel)
        session_layout.addWidget(self.expandedNewButton)
        session_layout.addWidget(self.expandedRenameButton)
        session_layout.addWidget(self.expandedDeleteButton)
        body.addWidget(session_panel)

        conversation_panel = QWidget(self.expandedPage)
        conversation_layout = QVBoxLayout(conversation_panel)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(8)
        self.expandedChatCard = HeaderCardWidget(conversation_panel)
        self.expandedChatCard.setTitle(self.tr("对话内容 · Markdown 安全渲染"))
        self.expandedTranscript = TextBrowser(self.expandedChatCard)
        self.expandedTranscript.setOpenExternalLinks(False)
        self.expandedTranscript.setOpenLinks(False)
        self.expandedTranscript.anchorClicked.connect(self._openSafeLink)
        self.expandedTranscript.setMinimumHeight(180)
        self.expandedChatCard.viewLayout.addWidget(self.expandedTranscript)
        conversation_layout.addWidget(self.expandedChatCard, stretch=1)

        input_layout = QHBoxLayout()
        self.expandedInputEdit = TextEdit(conversation_panel)
        self.expandedInputEdit.setPlaceholderText(self.tr("输入消息…"))
        self.expandedInputEdit.setMaximumHeight(105)
        expanded_buttons = QVBoxLayout()
        self.expandedSendButton = PrimaryPushButton(
            FluentIcon.SEND, self.tr("发送"), conversation_panel
        )
        self.expandedCancelButton = PushButton(
            FluentIcon.CANCEL, self.tr("取消"), conversation_panel
        )
        self.expandedCancelButton.setVisible(False)
        expanded_buttons.addWidget(self.expandedSendButton)
        expanded_buttons.addWidget(self.expandedCancelButton)
        expanded_buttons.addStretch(1)
        input_layout.addWidget(self.expandedInputEdit, stretch=1)
        input_layout.addLayout(expanded_buttons)
        conversation_layout.addLayout(input_layout)
        body.addWidget(conversation_panel, stretch=1)
        page_layout.addLayout(body, stretch=1)

        self.collapseConversationButton.clicked.connect(self.showCompactPage)
        self.expandedNewButton.clicked.connect(self.createConversation)
        self.expandedRenameButton.clicked.connect(self.renameConversation)
        self.expandedDeleteButton.clicked.connect(self.deleteConversation)
        self.expandedSendButton.clicked.connect(
            lambda: self._sendMessageFrom(self.expandedInputEdit)
        )
        self.expandedCancelButton.clicked.connect(self.cancelRequest)

    def _activeSession(self):
        return self.conversationState.active

    def _syncActiveSession(self) -> None:
        session = self._activeSession()
        session.messages = self.messages[-200:]
        session.assistant_meta = self.assistantMeta[-200:]
        session.updated_at = time.time()

    def _bindActiveSession(self) -> None:
        session = self._activeSession()
        self.messages = session.messages
        self.assistantMeta = session.assistant_meta

    def _persistConversations(self) -> bool:
        try:
            self._syncActiveSession()
            self.conversationStore.save(self.conversationState)
            return True
        except (OSError, TypeError, ValueError) as error:
            InfoBar.error(
                self.tr("无法保存对话"), str(error), parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return False

    def _refreshSessionControls(self) -> None:
        self._switchingSession = True
        try:
            sessions = self.conversationState.sessions
            active_index = next(
                index for index, one in enumerate(sessions)
                if one.id == self.conversationState.active_session_id
            )
            self.sessionCombo.clear()
            self.sessionCombo.addItems([one.title for one in sessions])
            self.sessionCombo.setCurrentIndex(active_index)
            self.expandedSessionList.clear()
            self.expandedSessionList.addItems([one.title for one in sessions])
            self.expandedSessionList.setCurrentRow(active_index)
            self.expandedDeleteButton.setEnabled(len(sessions) > 1)
        finally:
            self._switchingSession = False

    def _switchConversation(self, index: int) -> bool:
        if self._switchingSession or not 0 <= index < len(self.conversationState.sessions):
            return False
        target = self.conversationState.sessions[index]
        if target.id == self.conversationState.active_session_id:
            return True
        if self.requestThread is not None and self.requestThread.isRunning():
            InfoBar.warning(
                self.tr("暂时不能切换对话"),
                self.tr("当前请求仍在进行；取消或等待完成后再切换，回答会保留在原对话。"),
                parent=self,
            )
            self._refreshSessionControls()
            return False
        self._syncActiveSession()
        self.conversationState.active_session_id = target.id
        self._bindActiveSession()
        self._requestError = ""
        self._requestState = "idle"
        self.statusLabel.setText(self.tr("就绪"))
        self.expandedStatusLabel.setText(self.tr("就绪"))
        self._persistConversations()
        self._refreshSessionControls()
        self._renderTranscript()
        return True

    @pyqtSlot(int)
    def _onSessionComboChanged(self, index: int) -> None:
        self._switchConversation(index)

    @pyqtSlot(int)
    def _onExpandedSessionChanged(self, index: int) -> None:
        self._switchConversation(index)

    @pyqtSlot()
    def createConversation(self) -> None:
        if self.requestThread is not None and self.requestThread.isRunning():
            InfoBar.warning(
                self.tr("暂时不能新建对话"), self.tr("请先取消或等待当前请求完成。"), parent=self
            )
            return
        self._syncActiveSession()
        session = self.conversationStore.new_session()
        self.conversationState.sessions.append(session)
        self.conversationState.active_session_id = session.id
        self._bindActiveSession()
        self._requestError = ""
        self._requestState = "idle"
        self.statusLabel.setText(self.tr("就绪"))
        self.expandedStatusLabel.setText(self.tr("就绪"))
        self._persistConversations()
        self._refreshSessionControls()
        self._renderTranscript()

    @pyqtSlot()
    def renameConversation(self) -> None:
        if self.requestThread is not None and self.requestThread.isRunning():
            InfoBar.warning(
                self.tr("暂时不能重命名"), self.tr("请先取消或等待当前请求完成。"), parent=self
            )
            return
        session = self._activeSession()
        title, accepted = QInputDialog.getText(
            self, self.tr("重命名对话"), self.tr("对话名称"), text=session.title
        )
        title = " ".join(str(title).split())[:80]
        if not accepted or not title:
            return
        session.title = title
        session.updated_at = time.time()
        self._persistConversations()
        self._refreshSessionControls()

    @pyqtSlot()
    def deleteConversation(self) -> None:
        if len(self.conversationState.sessions) <= 1:
            return
        if self.requestThread is not None and self.requestThread.isRunning():
            InfoBar.warning(
                self.tr("暂时不能删除"), self.tr("请先取消或等待当前请求完成。"), parent=self
            )
            return
        from qfluentwidgets import MessageBox
        box = MessageBox(
            self.tr("删除本地对话"),
            self.tr(f"确定删除“{self._activeSession().title}”及其本地历史吗？"),
            self,
        )
        box.yesButton.setText(self.tr("删除"))
        box.cancelButton.setText(self.tr("取消"))
        if box.exec():
            self._deleteCurrentConversation()

    def _deleteCurrentConversation(self) -> None:
        current_id = self.conversationState.active_session_id
        index = next(
            index for index, one in enumerate(self.conversationState.sessions)
            if one.id == current_id
        )
        self.conversationState.sessions.pop(index)
        target_index = min(index, len(self.conversationState.sessions) - 1)
        self.conversationState.active_session_id = self.conversationState.sessions[target_index].id
        self._bindActiveSession()
        self._requestError = ""
        self._requestState = "idle"
        self._persistConversations()
        self._refreshSessionControls()
        self._renderTranscript()

    @pyqtSlot()
    def showExpandedConversation(self) -> None:
        self.expandedInputEdit.setPlainText(self.inputEdit.toPlainText())
        self._copyScrollPosition(self.transcript, self.expandedTranscript)
        self.pageStack.setCurrentWidget(
            self.expandedPage,
            duration=240,
            easingCurve=QEasingCurve.OutCubic,
        )

    @pyqtSlot()
    def showCompactPage(self) -> None:
        self.inputEdit.setPlainText(self.expandedInputEdit.toPlainText())
        self._copyScrollPosition(self.expandedTranscript, self.transcript)
        self.pageStack.setCurrentWidget(
            self.compactPage,
            needPopOut=True,
            duration=220,
            easingCurve=QEasingCurve.OutCubic,
        )

    @staticmethod
    def _copyScrollPosition(source: TextBrowser, target: TextBrowser) -> None:
        source_bar = source.verticalScrollBar()
        maximum = source_bar.maximum()
        ratio = source_bar.value() / maximum if maximum else 1.0

        def apply() -> None:
            if sip.isdeleted(target):
                return
            target_bar = target.verticalScrollBar()
            target_bar.setValue(round(target_bar.maximum() * ratio))

        QTimer.singleShot(0, apply)

    def _loadProfileIntoForm(self) -> None:
        self._loadingProfile = True
        try:
            self.baseUrlEdit.setText(self.profile.base_url)
            self.protocolCombo.setCurrentIndex(max(0, next(
                (index for index, one in enumerate(self.PROTOCOLS) if one[0] == self.profile.protocol), 0
            )))
            self.modelCombo.clear()
            self.modelCombo.addItem(self.profile.model)
            self.modelCombo.setCurrentText(self.profile.model)
            self.apiKeyEdit.setText(self.store.get_secret(self.profile.id))
            for capability_id, checkbox in self.capabilityChecks.items():
                checkbox.setChecked(capability_id in self.profile.capability_ids)
            self.searchEngineCombo.setCurrentIndex(max(0, next(
                (index for index, one in enumerate(SEARCH_ENGINES) if one[0] == self.profile.search_engine), 0
            )))
            self.searchEndpointEdit.setText(self.profile.search_endpoint)
            self.searchLimitCombo.setCurrentText(str(self.profile.search_result_limit))
            self._updateSearchControls()
            self._onProtocolChanged(self.protocolCombo.currentIndex())
        finally:
            self._loadingProfile = False

    def _currentPreset(self):
        return PRESETS[min(max(self.presetCombo.currentIndex(), 0), len(PRESETS) - 1)]

    def _currentProtocol(self) -> str:
        index = min(max(self.protocolCombo.currentIndex(), 0), len(self.PROTOCOLS) - 1)
        return self.PROTOCOLS[index][0]

    def _currentSearchEngine(self) -> str:
        index = min(max(self.searchEngineCombo.currentIndex(), 0), len(SEARCH_ENGINES) - 1)
        return SEARCH_ENGINES[index][0]

    @pyqtSlot(int)
    def _onPresetChanged(self, _index: int) -> None:
        preset = self._currentPreset()
        self.baseUrlEdit.setText(preset.base_url)
        protocol_index = next(index for index, one in enumerate(self.PROTOCOLS) if one[0] == preset.protocol)
        self.protocolCombo.setCurrentIndex(protocol_index)
        self.modelCombo.setCurrentText(preset.default_model)
        self.modelStatusLabel.setText(self.tr("已应用快速配置；协议仍可单独修改"))

    @pyqtSlot(int)
    def _onProtocolChanged(self, _index: int) -> None:
        is_ollama = self._currentProtocol() == "ollama"
        self.downloadModelButton.setEnabled(is_ollama)
        self.downloadModelButton.setToolTip(
            self.tr("下载到本机 Ollama") if is_ollama else self.tr("当前协议不支持本地下载")
        )

    @pyqtSlot(int)
    def _onSearchEngineChanged(self, _index: int) -> None:
        if self._currentSearchEngine() == "duckduckgo":
            self.searchEndpointEdit.setText("https://html.duckduckgo.com/html/")
        elif "duckduckgo.com" in self.searchEndpointEdit.text():
            self.searchEndpointEdit.setText(self._lastSearxngEndpoint)
        self._updateSearchControls()
        if not self._loadingProfile:
            self._persistSearchPreferences()

    @pyqtSlot()
    def _updateSearchControls(self) -> None:
        enabled = self.capabilityChecks["web_search"].isChecked()
        needs_searxng = self._currentSearchEngine() != "duckduckgo"
        self.searchEngineCombo.setEnabled(enabled)
        self.searchEndpointEdit.setEnabled(enabled and needs_searxng)
        self.searchEndpointEdit.setPlaceholderText(
            self.tr("填写 SearXNG 根地址，例如 https://search.example")
            if needs_searxng else "https://html.duckduckgo.com/html/"
        )
        self.searchLimitCombo.setEnabled(enabled)

    def _persistCapabilityPreferences(self, *_args) -> None:
        if self._loadingProfile:
            return
        try:
            profile = replace(self.profile, capability_ids=self._selectedCapabilityIds())
            self.store.save_profiles([profile])
        except Exception as error:
            self.capabilityStatusLabel.setText(self.tr(f"能力偏好未保存：{error}"))
            return
        self.profile = profile
        names = [one.name for one in CAPABILITIES if one.id in profile.capability_ids]
        self.capabilityStatusLabel.setText(
            self.tr("已保存能力偏好：") + "、".join(names)
            if names else self.tr("全部数据能力关闭；只发送你输入的对话文本。")
        )

    def _persistSearchPreferences(self, *_args) -> None:
        if self._loadingProfile:
            return
        engine = self._currentSearchEngine()
        endpoint = self.searchEndpointEdit.text().strip()
        if engine != "duckduckgo" and endpoint:
            self._lastSearxngEndpoint = endpoint
        try:
            profile = replace(
                self.profile,
                search_engine=engine,
                search_endpoint=endpoint,
                search_result_limit=int(self.searchLimitCombo.currentText() or 5),
            )
            self.store.save_profiles([profile])
        except Exception:
            if engine != "duckduckgo":
                self.capabilityStatusLabel.setText(
                    self.tr("已选择主流引擎；填写有效的 SearXNG HTTPS 地址后会自动记住。")
                )
            return
        self.profile = profile

    def _selectedCapabilityIds(self) -> tuple[str, ...]:
        return tuple(one.id for one in CAPABILITIES if self.capabilityChecks[one.id].isChecked())

    def _profileFromForm(self) -> AIProfile:
        return replace(
            self.profile,
            preset_id=self._currentPreset().id,
            protocol=self._currentProtocol(),
            base_url=self.baseUrlEdit.text().strip(),
            model=self.modelCombo.currentText().strip(),
            capability_ids=self._selectedCapabilityIds(),
            search_engine=self._currentSearchEngine(),
            search_endpoint=self.searchEndpointEdit.text().strip(),
            search_result_limit=int(self.searchLimitCombo.currentText() or 5),
        )

    def _providerConfig(self, *, allow_empty_model: bool = False) -> ProviderConfig:
        model = self.modelCombo.currentText().strip()
        return ProviderConfig(
            protocol=self._currentProtocol(),
            base_url=self.baseUrlEdit.text().strip(),
            model=model or ("catalog-placeholder" if allow_empty_model else ""),
            api_key=self.apiKeyEdit.text().strip(),
            max_output_tokens=self.profile.max_output_tokens,
            temperature=self.profile.temperature,
        )

    @pyqtSlot()
    def saveConfiguration(self) -> bool:
        try:
            profile = self._profileFromForm()
            self.store.save_profiles([profile])
            persistence = self.store.set_secret(profile.id, self.apiKeyEdit.text())
        except Exception as error:
            InfoBar.error(
                self.tr("无法保存 AI 配置"), str(error), parent=self,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return False
        self.profile = profile
        if persistence == SecretPersistence.KEYRING:
            self.storageLabel.setText(self.tr("API Key 已保存到系统密码管理器"))
        else:
            self.storageLabel.setText(self.tr("系统密码管理器不可用；API Key 仅保留在本次运行内存中"))
        enabled_names = [one.name for one in CAPABILITIES if one.id in profile.capability_ids]
        self.capabilityStatusLabel.setText(
            self.tr("本次已授权：") + "、".join(enabled_names)
            if enabled_names else self.tr("全部数据能力关闭；只发送你输入的对话文本。")
        )
        return True

    @pyqtSlot()
    def refreshModels(self) -> None:
        if self.modelListThread is not None and self.modelListThread.isRunning():
            return
        config = self._providerConfig(allow_empty_model=True)
        self.refreshModelsButton.setEnabled(False)
        self.modelStatusLabel.setText(self.tr("正在获取模型列表…"))
        thread = _ModelListThread(config, self)
        self.modelListThread = thread
        thread.succeeded.connect(self._onModelsLoaded)
        thread.failed.connect(self._onModelOperationError)
        thread.finished.connect(lambda current=thread: self._onModelListFinished(current))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _onModelListFinished(self, thread: QThread) -> None:
        if self.modelListThread is thread:
            self.modelListThread = None
        self.refreshModelsButton.setEnabled(True)

    @pyqtSlot(list)
    def _onModelsLoaded(self, models: list[str]) -> None:
        current = self.modelCombo.currentText().strip()
        self.modelCombo.clear()
        self.modelCombo.addItems(models)
        if current and current not in models:
            self.modelCombo.addItem(current)
        self.modelCombo.setCurrentText(current or (models[0] if models else ""))
        self.modelStatusLabel.setText(self.tr(f"已找到 {len(models)} 个模型，可用右侧箭头选择"))

    @pyqtSlot()
    def _onDownloadModelClicked(self) -> None:
        if self.modelPullThread is not None and self.modelPullThread.isRunning():
            self.modelPullThread.cancel()
            self.modelStatusLabel.setText(self.tr("正在取消模型下载…"))
            return
        if self._currentProtocol() != "ollama":
            InfoBar.warning(self.tr("无法下载"), self.tr("只有 Ollama 协议支持本地模型下载"), parent=self)
            return
        model = self.modelCombo.currentText().strip()
        if not model:
            InfoBar.warning(self.tr("无法下载"), self.tr("请先输入要下载的 Ollama 模型名"), parent=self)
            return
        if not self.saveConfiguration():
            return
        from qfluentwidgets import MessageBox
        box = MessageBox(
            self.tr("下载本地模型"),
            self.tr(f"将通过本机 Ollama 下载“{model}”。模型可能占用数 GB 空间，是否继续？"),
            self,
        )
        box.yesButton.setText(self.tr("开始下载"))
        box.cancelButton.setText(self.tr("取消"))
        if not box.exec():
            return
        self._startModelPull(model)

    def _startModelPull(self, model: str) -> None:
        thread = _ModelPullThread(self._providerConfig(), model, self)
        self.modelPullThread = thread
        self.modelProgress.setVisible(True)
        self.modelProgress.setValue(0)
        self.downloadModelButton.setText(self.tr("取消下载"))
        thread.progressed.connect(self._onModelPullProgress)
        thread.succeeded.connect(lambda: self._onModelPullSucceeded(model))
        thread.failed.connect(self._onModelOperationError)
        thread.cancelled.connect(lambda: self.modelStatusLabel.setText(self.tr("模型下载已取消")))
        thread.finished.connect(lambda current=thread: self._onModelPullFinished(current))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @pyqtSlot(object)
    def _onModelPullProgress(self, progress) -> None:
        if progress.percent is None:
            self.modelProgress.setRange(0, 0)
            detail = progress.status
        else:
            self.modelProgress.setRange(0, 100)
            self.modelProgress.setValue(progress.percent)
            detail = f"{progress.status} · {progress.percent}%"
        self.modelStatusLabel.setText(detail)

    def _onModelPullSucceeded(self, model: str) -> None:
        self.modelCombo.setCurrentText(model)
        self.modelStatusLabel.setText(self.tr("模型下载完成，正在刷新可选列表…"))
        QTimer.singleShot(0, self.refreshModels)

    @pyqtSlot(str)
    def _onModelOperationError(self, message: str) -> None:
        self.modelStatusLabel.setText(message)
        InfoBar.error(self.tr("模型操作失败"), message, duration=5000, parent=self)

    def _onModelPullFinished(self, thread: QThread) -> None:
        if self.modelPullThread is thread:
            self.modelPullThread = None
        self.downloadModelButton.setText(self.tr("下载模型"))
        if self.modelProgress.maximum() == 0:
            self.modelProgress.setRange(0, 100)

    def _localCapabilityContext(self):
        from app.utils import accounts
        from app.utils.cache import cacheManager
        account_directory = None
        if accounts.current is not None:
            account_directory = Path(accounts.current.data_manager.path("placeholder")).parent
        return collect_local_context(
            self.profile.capability_ids,
            notification_path=cacheManager.path("notification.json"),
            account_directory=account_directory,
        )

    @pyqtSlot()
    def sendMessage(self) -> None:
        self._sendMessageFrom(self.inputEdit)

    def _sendMessageFrom(self, editor: TextEdit) -> None:
        if self.requestThread is not None and self.requestThread.isRunning():
            return
        content = editor.toPlainText().strip()
        if not content:
            InfoBar.warning(self.tr("无法发送"), self.tr("请先输入消息"), parent=self)
            return
        if len(content) > 200_000:
            InfoBar.warning(self.tr("消息过长"), self.tr("单条消息不能超过 200000 字符"), parent=self)
            return
        if not self.saveConfiguration():
            return
        try:
            local_context = self._localCapabilityContext()
        except Exception as error:
            InfoBar.error(self.tr("无法读取已授权数据"), str(error), parent=self)
            return
        if local_context.unavailable:
            names = [one.name for one in CAPABILITIES if one.id in local_context.unavailable]
            self.capabilityStatusLabel.setText(self.tr("本机暂无可用数据：") + "、".join(names))
            InfoBar.warning(
                self.tr("已授权数据不可用"),
                self.tr("以下缓存当前不存在或损坏，已停止发送，避免模型在没有数据时猜测：") + "、".join(names),
                parent=self,
                duration=6000,
            )
            return
        counts = dict(local_context.counts)
        loaded = [
            f"{one.name} {counts[one.id]} 条"
            for one in CAPABILITIES if one.id in counts
        ]
        if loaded:
            self.capabilityStatusLabel.setText(self.tr("本次实际载入：") + "、".join(loaded))

        config = self._providerConfig()
        session = self._activeSession()
        self.messages.append(ChatMessage("user", content))
        if len(self.messages) == 1 and session.title == "新对话":
            session.title = self.conversationStore.suggested_title(content)
            self._refreshSessionControls()
        editor.clear()
        if editor is self.inputEdit:
            self.expandedInputEdit.clear()
        else:
            self.inputEdit.clear()
        self._persistConversations()
        self._requestState = "searching" if "web_search" in self.profile.capability_ids else "thinking"
        self._requestError = ""
        self._requestStarted = time.monotonic()
        self._requestElapsed = 0.0
        self._lastTickSecond = -1
        self._requestSessionId = session.id
        history = self.messages[-40:]
        request_messages = [ChatMessage("system", self.profile.system_prompt), *history]
        search_settings = None
        if "web_search" in self.profile.capability_ids:
            search_settings = {
                "engine": self.profile.search_engine,
                "endpoint": self.profile.search_endpoint,
                "limit": self.profile.search_result_limit,
            }
        thread = _AIRequestThread(
            request_messages,
            config,
            search_query=content,
            search_settings=search_settings,
            local_context=local_context.text,
            session_id=session.id,
            parent=self,
        )
        self.requestThread = thread
        thread.stageChanged.connect(self._onRequestStageChanged)
        thread.succeeded.connect(self._onResult)
        thread.failed.connect(self._onError)
        thread.webSearchDisabled.connect(self._onWebSearchDisabled)
        thread.cancelled.connect(self._onRequestCancelled)
        thread.finished.connect(lambda current=thread: self._onFinished(current))
        thread.finished.connect(thread.deleteLater)
        self.sendButton.setEnabled(False)
        self.clearButton.setEnabled(False)
        self.cancelButton.setVisible(True)
        self.cancelButton.setEnabled(True)
        self.expandedSendButton.setEnabled(False)
        self.expandedNewButton.setEnabled(False)
        self.expandedRenameButton.setEnabled(False)
        self.expandedDeleteButton.setEnabled(False)
        self.expandedCancelButton.setVisible(True)
        self.expandedCancelButton.setEnabled(True)
        self.requestTimer.start()
        self._onRequestTick()
        thread.start()

    @pyqtSlot(str)
    def _onRequestStageChanged(self, stage: str) -> None:
        if self._requestState != "cancelling":
            self._requestState = stage
            self._renderTranscript()

    @pyqtSlot()
    def _onRequestTick(self) -> None:
        if not self._requestStarted:
            return
        self._requestElapsed = max(0.0, time.monotonic() - self._requestStarted)
        second = int(self._requestElapsed)
        if second == self._lastTickSecond:
            return
        self._lastTickSecond = second
        if self._requestState in {"thinking", "searching"} and second >= self.STUCK_SECONDS:
            self._requestState = "stuck"
        labels = {
            "searching": "正在联网搜索",
            "thinking": "模型正在思考",
            "stuck": "等待较久，模型可能繁忙或连接受阻",
            "cancelling": "正在取消",
        }
        if self._requestState in labels:
            status = f"{labels[self._requestState]} · {second} 秒"
            self.statusLabel.setText(status)
            self.expandedStatusLabel.setText(status)
        self._renderTranscript()

    @pyqtSlot()
    def cancelRequest(self) -> None:
        if self.requestThread is None or not self.requestThread.isRunning():
            return
        self._requestState = "cancelling"
        self.cancelButton.setEnabled(False)
        self.expandedCancelButton.setEnabled(False)
        self.requestThread.cancel()
        self._onRequestTick()

    @pyqtSlot(object)
    def _onResult(self, outcome: _AIRequestOutcome) -> None:
        self._updateElapsed()
        result = outcome.result
        session_id = getattr(outcome, "session_id", "") or self.conversationState.active_session_id
        session = next(
            (one for one in self.conversationState.sessions if one.id == session_id),
            None,
        )
        if session is None:
            return
        session.messages.append(ChatMessage("assistant", result.text))
        session.assistant_meta.append({
            "model": result.model,
            "elapsed": self._requestElapsed,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "search_count": outcome.search_count,
        })
        session.updated_at = time.time()
        if session.id == self.conversationState.active_session_id:
            self._bindActiveSession()
        self._requestState = "done"
        status = self.tr(f"回答完成 · {self._requestElapsed:.1f} 秒")
        self.statusLabel.setText(status)
        self.expandedStatusLabel.setText(status)
        self._persistConversations()
        self._renderTranscript()

    @pyqtSlot(object)
    def _onError(self, failure) -> None:
        message = failure.message if isinstance(failure, _AIRequestFailure) else str(failure)
        self._updateElapsed()
        self._requestState = "error"
        self._requestError = message
        status = self.tr(f"请求失败 · {self._requestElapsed:.1f} 秒")
        self.statusLabel.setText(status)
        self.expandedStatusLabel.setText(status)
        self._renderTranscript()
        InfoBar.error(
            self.tr("AI 请求失败"), message, duration=5000, parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    @pyqtSlot(object)
    def _onWebSearchDisabled(self, failure) -> None:
        message = failure.message if isinstance(failure, _AIRequestFailure) else str(failure)
        self.capabilityChecks["web_search"].setChecked(False)
        self._requestState = "error"
        self._requestError = message
        self._updateElapsed()
        status = self.tr(f"联网搜索已自动关闭 · {self._requestElapsed:.1f} 秒")
        self.statusLabel.setText(status)
        self.expandedStatusLabel.setText(status)
        self._renderTranscript()
        InfoBar.warning(
            self.tr("联网搜索已自动关闭"), message, duration=7000, parent=self,
            position=InfoBarPosition.TOP_RIGHT,
        )

    @pyqtSlot()
    def _onRequestCancelled(self) -> None:
        self._updateElapsed()
        self._requestState = "cancelled"
        status = self.tr(f"已取消 · {self._requestElapsed:.1f} 秒")
        self.statusLabel.setText(status)
        self.expandedStatusLabel.setText(status)
        self._renderTranscript()

    def _onFinished(self, thread: QThread) -> None:
        self._updateElapsed()
        self.requestTimer.stop()
        if self.requestThread is thread:
            self.requestThread = None
        self.sendButton.setEnabled(True)
        self.clearButton.setEnabled(True)
        self.cancelButton.setVisible(False)
        self.expandedSendButton.setEnabled(True)
        self.expandedNewButton.setEnabled(True)
        self.expandedRenameButton.setEnabled(True)
        self.expandedDeleteButton.setEnabled(len(self.conversationState.sessions) > 1)
        self.expandedCancelButton.setVisible(False)

    @pyqtSlot()
    def clearConversation(self) -> None:
        if self.requestThread is not None and self.requestThread.isRunning():
            return
        self.messages.clear()
        self.assistantMeta.clear()
        self._requestError = ""
        self._requestState = "idle"
        self.statusLabel.setText(self.tr("就绪"))
        self.expandedStatusLabel.setText(self.tr("就绪"))
        self._persistConversations()
        self._renderTranscript()

    @pyqtSlot(QUrl)
    def _openSafeLink(self, url: QUrl) -> None:
        parsed = urlparse(url.toString())
        if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
            QDesktopServices.openUrl(url)

    def _renderTranscript(self) -> None:
        dark = isDarkTheme()
        colors = {
            "body": "#F2F2F2" if dark else "#202124",
            "document": "#242424" if dark else "#FFFFFF",
            "user": "#173A5E" if dark else "#E3F0FF",
            "assistant": "#2A2D31" if dark else "#F1F3F5",
            "status": "#4B3A12" if dark else "#FFF3CD",
            "error": "#4A2020" if dark else "#FCE8E6",
            "meta": "#BCC3CC" if dark else "#5F6368",
            "pre": "#272822" if dark else "#F6F8FA",
            "pre_text": "#F8F8F2" if dark else "#24292F",
            "quote": "#C8D0D9" if dark else "#4F5963",
            "border": "#626A73" if dark else "#C8CCD0",
            "link": "#6CB6FF" if dark else "#1769AA",
        }
        style = f"""
        <style>
          body {{ font-family: sans-serif; margin: 10px; color: {colors['body']}; background-color: {colors['document']}; }}
          .message {{ margin: 8px 0; padding: 10px 12px; border-radius: 9px; }}
          .user {{ background: {colors['user']}; margin-left: 12%; }}
          .assistant {{ background: {colors['assistant']}; margin-right: 8%; }}
          .status {{ background: {colors['status']}; border-left: 4px solid #E6A700; }}
          .error {{ background: {colors['error']}; border-left: 4px solid #D93025; }}
          .speaker {{ font-weight: 600; margin-bottom: 5px; }}
          .meta {{ color: {colors['meta']}; font-size: 11px; margin-top: 7px; }}
          pre {{ background: {colors['pre']}; color: {colors['pre_text']}; padding: 8px; white-space: pre-wrap; }}
          code {{ font-family: monospace; }}
          blockquote {{ border-left: 3px solid {colors['border']}; padding-left: 8px; color: {colors['quote']}; }}
          table {{ border-collapse: collapse; }} th, td {{ border: 1px solid {colors['border']}; padding: 4px 7px; }}
          a {{ color: {colors['link']}; text-decoration: none; }}
        </style>
        """
        blocks = []
        assistant_index = 0
        for message in self.messages:
            if message.role not in {"user", "assistant"}:
                continue
            role_class = "user" if message.role == "user" else "assistant"
            speaker = self.tr("你") if message.role == "user" else self.tr("问舟")
            meta = ""
            if message.role == "assistant":
                details = self.assistantMeta[assistant_index] if assistant_index < len(self.assistantMeta) else {}
                assistant_index += 1
                parts = []
                if details.get("model"):
                    parts.append(html.escape(str(details["model"])))
                if details.get("elapsed") is not None:
                    parts.append(f"{float(details['elapsed']):.1f} 秒")
                if details.get("input_tokens") is not None or details.get("output_tokens") is not None:
                    parts.append(f"token {details.get('input_tokens', '?')} → {details.get('output_tokens', '?')}")
                if details.get("search_count"):
                    parts.append(f"联网结果 {details['search_count']} 条")
                if parts:
                    meta = f'<div class="meta">{" · ".join(parts)}</div>'
            blocks.append(
                f'<div class="message {role_class}"><div class="speaker">{speaker}</div>'
                f'{render_markdown_fragment(message.content, dark=dark)}{meta}</div>'
            )
        if self._requestState in {"searching", "thinking", "stuck", "cancelling"}:
            labels = {
                "searching": "正在联网搜索",
                "thinking": "模型正在思考",
                "stuck": "等待较久，可能是模型繁忙、网络受阻或服务卡住",
                "cancelling": "正在取消请求",
            }
            blocks.append(
                f'<div class="message status"><div class="speaker">问舟</div>'
                f'<p>{labels[self._requestState]} · {int(self._requestElapsed)} 秒</p></div>'
            )
        if self._requestError:
            blocks.append(
                f'<div class="message error"><div class="speaker">请求失败</div>'
                f'<p>{html.escape(self._requestError)}</p></div>'
            )
        if not blocks:
            blocks.append(
                '<div class="message assistant"><div class="speaker">问舟</div>'
                '<p>还没有对话。选择模型服务与能力开关后即可开始；所有数据能力默认关闭。</p></div>'
            )
        document = style + "".join(blocks)
        for transcript in (self.transcript, self.expandedTranscript):
            transcript.setHtml(document)
            cursor = transcript.textCursor()
            cursor.movePosition(cursor.End)
            transcript.setTextCursor(cursor)

    @pyqtSlot()
    def _onThemeChanged(self, *_args) -> None:
        self._applyThemeSurfaces()
        self._renderTranscript()

    def _applyThemeSurfaces(self) -> None:
        dark = isDarkTheme()
        page = "#202020" if dark else "#F3F3F3"
        transcript = "#242424" if dark else "#FFFFFF"
        text = "#F2F2F2" if dark else "#202124"
        self.compactPage.setStyleSheet(
            f"QWidget#wenzhouCompactPage {{ background-color: {page}; }}"
        )
        self.expandedPage.setStyleSheet(
            f"QWidget#wenzhouExpandedConversationPage {{ background-color: {page}; }}"
        )
        for browser in (self.transcript, self.expandedTranscript):
            browser.setStyleSheet(
                f"QTextBrowser {{ background-color: {transcript}; color: {text}; }}"
            )

    def closeEvent(self, event) -> None:
        try:
            self._syncActiveSession()
            self.conversationStore.save(self.conversationState)
        except (OSError, TypeError, ValueError):
            pass
        for thread in (self.requestThread, self.modelListThread, self.modelPullThread):
            if thread is None or not thread.isRunning():
                continue
            if hasattr(thread, "cancel"):
                thread.cancel()
            if not thread.wait(3000):
                # Last-resort shutdown protection: a blocking third-party HTTP
                # stack must not leave a QThread alive while Qt destroys it.
                thread.terminate()
                thread.wait(1000)
        super().closeEvent(event)

    def _updateElapsed(self) -> None:
        if self._requestStarted:
            self._requestElapsed = max(0.0, time.monotonic() - self._requestStarted)
