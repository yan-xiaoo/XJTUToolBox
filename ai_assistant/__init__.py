"""Provider-neutral AI assistant core used by the desktop UI."""

from .config import AIConfigStore, AIProfile, SecretPersistence
from .providers import (
    AIClient,
    AIProviderError,
    ChatMessage,
    ChatResult,
    PRESETS,
    ProviderConfig,
    ProviderPreset,
    ToolCall,
    ToolDefinition,
)
from .capabilities import CAPABILITIES, CapabilityContext, collect_local_context
from .model_catalog import ModelCatalogClient, ModelOperationCancelled, ModelPullProgress
from .conversations import (
    ConversationSession,
    ConversationState,
    ConversationStore,
)
from .web_search import (
    SEARCH_ENGINES,
    SearchAllSourcesVerificationRequired,
    SearchHumanVerificationRequired,
    SearchResult,
    WebSearchClient,
)

__all__ = [
    "AIClient",
    "AIConfigStore",
    "AIProfile",
    "AIProviderError",
    "ChatMessage",
    "ChatResult",
    "CAPABILITIES",
    "CapabilityContext",
    "collect_local_context",
    "ConversationSession",
    "ConversationState",
    "ConversationStore",
    "ModelCatalogClient",
    "ModelOperationCancelled",
    "ModelPullProgress",
    "PRESETS",
    "ProviderConfig",
    "ProviderPreset",
    "SecretPersistence",
    "SEARCH_ENGINES",
    "SearchAllSourcesVerificationRequired",
    "SearchResult",
    "SearchHumanVerificationRequired",
    "ToolCall",
    "ToolDefinition",
    "WebSearchClient",
]
