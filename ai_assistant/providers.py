"""Native adapters for mainstream LLM HTTP protocols.

Provider brands are presets; wire protocols are adapters.  Adding another
OpenAI-compatible vendor therefore requires data, not another request branch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence
from urllib.parse import quote, urlparse

import requests


Protocol = Literal["openai", "anthropic", "gemini", "ollama"]


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    protocol: Protocol
    base_url: str
    default_model: str
    key_required: bool = True


PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1", "deepseek-chat"),
    ProviderPreset("openai", "OpenAI", "openai", "https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderPreset("anthropic", "Anthropic Claude", "anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-5"),
    ProviderPreset("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
    ProviderPreset("qwen", "通义千问 DashScope", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ProviderPreset("zhipu", "智谱 GLM", "openai", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ProviderPreset("moonshot", "Moonshot Kimi", "openai", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ProviderPreset("siliconflow", "SiliconFlow", "openai", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
    ProviderPreset("mistral", "Mistral AI", "openai", "https://api.mistral.ai/v1", "mistral-small-latest"),
    ProviderPreset("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ProviderPreset("xai", "xAI", "openai", "https://api.x.ai/v1", "grok-3-mini"),
    ProviderPreset("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "openai/gpt-4.1-mini"),
    ProviderPreset("ollama", "Ollama 本地", "ollama", "http://127.0.0.1:11434/api", "qwen3:8b", False),
    ProviderPreset("custom-openai", "自定义 OpenAI-compatible", "openai", "https://", ""),
    ProviderPreset("custom-anthropic", "自定义 Anthropic Messages", "anthropic", "https://", ""),
    ProviderPreset("custom-gemini", "自定义 Gemini", "gemini", "https://", ""),
    ProviderPreset("custom-ollama", "自定义 Ollama", "ollama", "http://127.0.0.1:11434/api", "", False),
)

PRESET_BY_ID = {preset.id: preset for preset in PRESETS}


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple["ToolCall", ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class ToolCall:
    """Provider-neutral function call emitted by an assistant message."""

    id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-neutral function schema accepted by supported adapters."""

    name: str
    description: str
    input_schema: Mapping[str, object]


@dataclass(frozen=True)
class ProviderConfig:
    protocol: Protocol
    base_url: str
    model: str
    api_key: str = ""
    max_output_tokens: int = 2048
    temperature: float = 0.7


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    finish_reason: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: tuple[ToolCall, ...] = ()


class AIProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def preset_for(preset_id: str) -> ProviderPreset:
    try:
        return PRESET_BY_ID[preset_id]
    except KeyError as error:
        raise ValueError(f"Unknown AI provider preset: {preset_id}") from error


def validate_config(config: ProviderConfig) -> ProviderConfig:
    if config.protocol not in {"openai", "anthropic", "gemini", "ollama"}:
        raise ValueError("不支持的 AI 协议")
    parsed = urlparse(config.base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是完整的 HTTP(S) 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不得包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL 不得包含查询参数或片段，API Key 请填写在专用字段")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("非本机 AI 端点必须使用 HTTPS")
    if not config.model.strip() or len(config.model.strip()) > 200:
        raise ValueError("请填写有效的模型 ID")
    if not 1 <= int(config.max_output_tokens) <= 32768:
        raise ValueError("最大输出 token 必须在 1–32768 之间")
    if not 0 <= float(config.temperature) <= 2:
        raise ValueError("温度必须在 0–2 之间")
    if config.protocol != "ollama" and not config.api_key.strip():
        raise ValueError("请填写 API Key")
    return ProviderConfig(
        protocol=config.protocol,
        base_url=config.base_url.strip().rstrip("/"),
        model=config.model.strip(),
        api_key=config.api_key.strip(),
        max_output_tokens=int(config.max_output_tokens),
        temperature=float(config.temperature),
    )


def validate_messages(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    if not messages:
        raise ValueError("对话不能为空")
    result: list[ChatMessage] = []
    for message in messages:
        if message.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"不支持的消息角色：{message.role}")
        content = str(message.content).strip()
        calls = tuple(_validate_tool_call(one) for one in message.tool_calls)
        call_id = str(message.tool_call_id).strip()
        if message.role == "tool" and not call_id:
            raise ValueError("工具结果消息必须包含 tool_call_id")
        if message.role != "assistant" and calls:
            raise ValueError("只有 assistant 消息可以包含工具调用")
        if not content and not calls:
            continue
        if len(content) > 200_000:
            raise ValueError("单条消息过长")
        result.append(ChatMessage(message.role, content, calls, call_id))
    if not result or not any(one.role == "user" for one in result):
        raise ValueError("对话中至少需要一条用户消息")
    return result


def validate_tools(tools: Sequence[ToolDefinition]) -> list[ToolDefinition]:
    result: list[ToolDefinition] = []
    names: set[str] = set()
    for tool in tools:
        name = str(tool.name).strip()
        description = str(tool.description).strip()
        schema = tool.input_schema
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError(f"无效的工具名称：{name}")
        if name in names:
            raise ValueError(f"工具名称重复：{name}")
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise ValueError(f"工具 {name} 的 input_schema 必须是 object JSON Schema")
        if len(description) > 4_000:
            raise ValueError(f"工具 {name} 的说明过长")
        # Fail early if a custom Mapping contains values that cannot be sent as JSON.
        json.dumps(schema, ensure_ascii=False)
        result.append(ToolDefinition(name, description, dict(schema)))
        names.add(name)
    return result


def _validate_tool_call(call: ToolCall) -> ToolCall:
    call_id = str(call.id).strip()
    name = str(call.name).strip()
    if not call_id or len(call_id) > 200:
        raise ValueError("无效的工具调用 ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError(f"无效的工具名称：{name}")
    if not isinstance(call.arguments, Mapping):
        raise ValueError(f"工具 {name} 的参数必须是 JSON object")
    json.dumps(call.arguments, ensure_ascii=False)
    return ToolCall(call_id, name, dict(call.arguments))


class AIClient:
    """Synchronous protocol client; the Qt layer runs it in a worker thread."""

    def __init__(self, session: requests.Session | None = None, timeout: tuple[int, int] = (20, 120)):
        self.session = session or requests.Session()
        self.timeout = timeout

    def complete(
        self,
        messages: Sequence[ChatMessage],
        config: ProviderConfig,
        tools: Sequence[ToolDefinition] = (),
    ) -> ChatResult:
        checked = validate_config(config)
        normalized_messages = validate_messages(messages)
        normalized_tools = validate_tools(tools)
        if normalized_tools and checked.protocol not in {"openai", "anthropic"}:
            raise ValueError("当前协议尚未启用工具调用；文本对话仍可正常使用")
        adapter = {
            "openai": self._openai,
            "anthropic": self._anthropic,
            "gemini": self._gemini,
            "ollama": self._ollama,
        }[checked.protocol]
        try:
            return adapter(normalized_messages, checked, normalized_tools)
        except AIProviderError:
            raise
        except requests.Timeout as error:
            raise AIProviderError("timeout", "AI 服务请求超时，请稍后重试") from error
        except requests.ConnectionError as error:
            raise AIProviderError("connection", "无法连接 AI 服务，请检查网络和 Base URL") from error
        except requests.RequestException as error:
            raise AIProviderError("network", f"AI 网络请求失败：{type(error).__name__}") from error
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("invalid_response", "AI 服务返回了无法解析的响应") from error

    def _post(self, url: str, config: ProviderConfig, *, headers: dict, payload: dict):
        response = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
        if not 200 <= response.status_code < 300:
            raise self._http_error(response, config.api_key)
        try:
            return response.json()
        except ValueError as error:
            raise AIProviderError("invalid_response", "AI 服务返回的不是有效 JSON") from error

    @staticmethod
    def _http_error(response, api_key: str) -> AIProviderError:
        status = int(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = ""
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("type") or "")
            elif error:
                message = str(error)
            message = message or str(payload.get("message") or "")
        if api_key:
            message = message.replace(api_key, "***")
        message = " ".join(message.split())[:400]
        if status in {401, 403}:
            code, fallback = "authentication", "API Key 无效或无权访问该模型"
        elif status == 429:
            code, fallback = "rate_limit", "AI 服务限流或额度不足"
        elif status >= 500:
            code, fallback = "upstream", "AI 服务暂时不可用"
        else:
            code, fallback = "request", f"AI 服务拒绝请求（HTTP {status}）"
        return AIProviderError(code, message or fallback, status=status)

    def _openai(
        self,
        messages: Sequence[ChatMessage],
        config: ProviderConfig,
        tools: Sequence[ToolDefinition],
    ) -> ChatResult:
        payload = {
            "model": config.model,
            "messages": [_openai_message(one) for one in messages],
            "max_tokens": config.max_output_tokens,
            "temperature": config.temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in tools
            ]
        data = self._post(
            f"{config.base_url}/chat/completions",
            config,
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            payload=payload,
        )
        choice = data["choices"][0]
        response_message = choice["message"]
        content = response_message.get("content")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        text = str(content or "").strip()
        tool_calls = tuple(_openai_tool_call(one) for one in response_message.get("tool_calls") or [])
        if not text and not tool_calls:
            raise AIProviderError("empty_response", "AI 服务返回了空内容")
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            model=str(data.get("model") or config.model),
            finish_reason=str(choice.get("finish_reason") or ""),
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
            tool_calls=tool_calls,
        )

    def _anthropic(
        self,
        messages: Sequence[ChatMessage],
        config: ProviderConfig,
        tools: Sequence[ToolDefinition],
    ) -> ChatResult:
        system = "\n\n".join(one.content for one in messages if one.role == "system")
        conversation = [_anthropic_message(one) for one in messages if one.role != "system"]
        payload = {
            "model": config.model,
            "messages": conversation,
            "max_tokens": config.max_output_tokens,
            "temperature": config.temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": dict(tool.input_schema),
                }
                for tool in tools
            ]
        data = self._post(
            f"{config.base_url}/messages",
            config,
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        blocks = data.get("content") or []
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        tool_calls = tuple(
            _validate_tool_call(ToolCall(
                str(block.get("id") or ""),
                str(block.get("name") or ""),
                block.get("input") if isinstance(block.get("input"), dict) else {},
            ))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
        if not text and not tool_calls:
            raise AIProviderError("empty_response", "Anthropic 返回了空内容")
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            model=str(data.get("model") or config.model),
            finish_reason=str(data.get("stop_reason") or ""),
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            tool_calls=tool_calls,
        )

    def _gemini(
        self,
        messages: Sequence[ChatMessage],
        config: ProviderConfig,
        _tools: Sequence[ToolDefinition],
    ) -> ChatResult:
        system = "\n\n".join(one.content for one in messages if one.role == "system")
        contents = [
            {
                "role": "model" if one.role == "assistant" else "user",
                "parts": [{"text": one.content}],
            }
            for one in messages
            if one.role in {"user", "assistant"}
        ]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": config.max_output_tokens,
                "temperature": config.temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        model = quote(config.model, safe="-_.")
        data = self._post(
            f"{config.base_url}/models/{model}:generateContent",
            config,
            headers={"Content-Type": "application/json", "x-goog-api-key": config.api_key},
            payload=payload,
        )
        candidate = (data.get("candidates") or [])[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
        if not text:
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            detail = f"：{block_reason}" if block_reason else ""
            raise AIProviderError("empty_response", f"Gemini 未返回可显示内容{detail}")
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            text=text,
            model=config.model,
            finish_reason=str(candidate.get("finishReason") or ""),
            input_tokens=_optional_int(usage.get("promptTokenCount")),
            output_tokens=_optional_int(usage.get("candidatesTokenCount")),
        )

    def _ollama(
        self,
        messages: Sequence[ChatMessage],
        config: ProviderConfig,
        _tools: Sequence[ToolDefinition],
    ) -> ChatResult:
        data = self._post(
            f"{config.base_url}/chat",
            config,
            headers={"Content-Type": "application/json"},
            payload={
                "model": config.model,
                "messages": [{"role": one.role, "content": one.content} for one in messages],
                "stream": False,
                "options": {"temperature": config.temperature, "num_predict": config.max_output_tokens},
            },
        )
        text = str((data.get("message") or {}).get("content") or "").strip()
        if not text:
            raise AIProviderError("empty_response", "Ollama 返回了空内容")
        return ChatResult(
            text=text,
            model=str(data.get("model") or config.model),
            finish_reason=str(data.get("done_reason") or ""),
            input_tokens=_optional_int(data.get("prompt_eval_count")),
            output_tokens=_optional_int(data.get("eval_count")),
        )


def _optional_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _openai_message(message: ChatMessage) -> dict[str, object]:
    payload: dict[str, object] = {"role": message.role, "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        payload["content"] = message.content or None
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":")),
                },
            }
            for call in message.tool_calls
        ]
    if message.role == "tool":
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _anthropic_message(message: ChatMessage) -> dict[str, object]:
    if message.role == "tool":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }],
        }
    if message.role == "assistant" and message.tool_calls:
        blocks: list[dict[str, object]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        blocks.extend(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": dict(call.arguments)}
            for call in message.tool_calls
        )
        return {"role": "assistant", "content": blocks}
    return {"role": message.role, "content": message.content}


def _openai_tool_call(payload: object) -> ToolCall:
    if not isinstance(payload, dict):
        raise ValueError("invalid OpenAI tool call")
    function = payload.get("function")
    if not isinstance(function, dict):
        raise ValueError("invalid OpenAI function call")
    arguments = function.get("arguments") or "{}"
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("OpenAI tool arguments are not an object")
    return _validate_tool_call(ToolCall(str(payload.get("id") or ""), str(function.get("name") or ""), arguments))
