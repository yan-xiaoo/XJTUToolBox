"""AI profile metadata and secret storage.

API keys are never serialized into the JSON profile file.  If the operating
system keyring is unavailable, a key may be retained in memory for the current
process only and the UI reports that limitation explicitly.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import keyring
import platformdirs

from .providers import PRESET_BY_ID, Protocol, preset_for
from .capabilities import validate_capability_ids
from .web_search import DUCKDUCKGO_ENDPOINT, validate_search_settings


SCHEMA_VERSION = 2
KEYRING_SERVICE = "XJTUToolbox.AI"
DEFAULT_ASSISTANT_NAME = "问舟"
DEFAULT_SYSTEM_PROMPT = "你是仙交百宝箱中的 AI 助手问舟。请准确、坦诚地回答，不确定时明确说明。"
LEGACY_ASSISTANT_NAME = "屁岱"
LEGACY_SYSTEM_PROMPT = "你是仙交百宝箱中的 AI 助手屁岱。请准确、坦诚地回答，不确定时明确说明。"


class SecretPersistence(Enum):
    KEYRING = "keyring"
    SESSION = "session"


@dataclass(frozen=True)
class AIProfile:
    id: str
    name: str
    preset_id: str
    protocol: Protocol
    base_url: str
    model: str
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_output_tokens: int = 2048
    temperature: float = 0.7
    capability_ids: tuple[str, ...] = ()
    search_engine: str = "duckduckgo"
    search_endpoint: str = DUCKDUCKGO_ENDPOINT
    search_result_limit: int = 5

    @classmethod
    def default(cls) -> "AIProfile":
        preset = preset_for("deepseek")
        return cls(
            id="default",
            name=DEFAULT_ASSISTANT_NAME,
            preset_id=preset.id,
            protocol=preset.protocol,
            base_url=preset.base_url,
            model=preset.default_model,
        )


def validate_profile(profile: AIProfile) -> AIProfile:
    preset = PRESET_BY_ID.get(profile.preset_id)
    if preset is None:
        raise ValueError(f"未知的提供商预设：{profile.preset_id}")
    if profile.protocol not in {"openai", "anthropic", "gemini", "ollama"}:
        raise ValueError("未知的 AI 协议")
    profile_id = str(profile.id).strip()
    if not profile_id or len(profile_id) > 80:
        raise ValueError("无效的 AI 配置 ID")
    name = " ".join(str(profile.name).split())[:40] or DEFAULT_ASSISTANT_NAME
    if not 1 <= int(profile.max_output_tokens) <= 32768:
        raise ValueError("最大输出 token 必须在 1–32768 之间")
    if not 0 <= float(profile.temperature) <= 2:
        raise ValueError("温度必须在 0–2 之间")
    parsed_url = urlparse(str(profile.base_url).strip())
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Base URL 必须是完整的 HTTP(S) 地址")
    if parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        raise ValueError("Base URL 不得包含凭据、查询参数或片段")
    if parsed_url.scheme == "http" and parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("非本机 AI 端点必须使用 HTTPS")
    model = str(profile.model).strip()
    if not model or len(model) > 200:
        raise ValueError("请填写有效的模型 ID")
    capability_ids = validate_capability_ids(profile.capability_ids)
    search_engine, search_endpoint = validate_search_settings(
        profile.search_engine,
        profile.search_endpoint,
    )
    if not 1 <= int(profile.search_result_limit) <= 10:
        raise ValueError("搜索结果数量必须在 1–10 之间")
    return AIProfile(
        id=profile_id,
        name=name,
        preset_id=profile.preset_id,
        protocol=profile.protocol,
        base_url=str(profile.base_url).strip().rstrip("/"),
        model=model,
        system_prompt=str(profile.system_prompt).strip()[:20_000],
        max_output_tokens=int(profile.max_output_tokens),
        temperature=float(profile.temperature),
        capability_ids=capability_ids,
        search_engine=search_engine,
        search_endpoint=search_endpoint,
        search_result_limit=int(profile.search_result_limit),
    )


class AIConfigStore:
    def __init__(self, path: str | os.PathLike | None = None, keyring_backend=None):
        if path is None:
            data_dir = platformdirs.user_data_dir("XJTUToolbox", ensure_exists=True)
            path = Path(data_dir) / "ai_profiles.json"
        self.path = Path(path)
        self.keyring = keyring_backend or keyring
        self._session_secrets: dict[str, str] = {}
        self.last_error = ""

    def load_profiles(self) -> list[AIProfile]:
        self.last_error = ""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") not in {1, SCHEMA_VERSION}:
                raise ValueError("不支持的 AI 配置版本")
            profiles = [
                validate_profile(self._migrate_legacy_branding(AIProfile(**one)))
                for one in payload.get("profiles", [])
            ]
            if not profiles:
                return [AIProfile.default()]
            ids = [one.id for one in profiles]
            if len(ids) != len(set(ids)):
                raise ValueError("AI 配置 ID 重复")
            return profiles
        except FileNotFoundError:
            return [AIProfile.default()]
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.last_error = f"{type(error).__name__}: {error}"
            return [AIProfile.default()]

    def save_profiles(self, profiles: list[AIProfile]) -> None:
        checked = [validate_profile(one) for one in profiles]
        ids = [one.id for one in checked]
        if len(ids) != len(set(ids)):
            raise ValueError("AI 配置 ID 重复")
        payload = {"version": SCHEMA_VERSION, "profiles": [asdict(one) for one in checked]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def set_secret(self, profile_id: str, api_key: str) -> SecretPersistence:
        profile_id = str(profile_id).strip()
        secret = str(api_key).strip()
        if not profile_id:
            raise ValueError("配置 ID 不能为空")
        if not secret:
            self.delete_secret(profile_id)
            return SecretPersistence.SESSION
        try:
            self.keyring.set_password(KEYRING_SERVICE, profile_id, secret)
        except Exception:
            self._session_secrets[profile_id] = secret
            return SecretPersistence.SESSION
        self._session_secrets.pop(profile_id, None)
        return SecretPersistence.KEYRING

    def get_secret(self, profile_id: str) -> str:
        if profile_id in self._session_secrets:
            return self._session_secrets[profile_id]
        try:
            return self.keyring.get_password(KEYRING_SERVICE, profile_id) or ""
        except Exception:
            return ""

    def delete_secret(self, profile_id: str) -> None:
        self._session_secrets.pop(profile_id, None)
        try:
            self.keyring.delete_password(KEYRING_SERVICE, profile_id)
        except Exception:
            pass

    @staticmethod
    def _migrate_legacy_branding(profile: AIProfile) -> AIProfile:
        """Rename only untouched legacy defaults; preserve user custom text."""

        updates = {}
        if profile.name == LEGACY_ASSISTANT_NAME:
            updates["name"] = DEFAULT_ASSISTANT_NAME
        if profile.system_prompt == LEGACY_SYSTEM_PROMPT:
            updates["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        return replace(profile, **updates) if updates else profile

    @staticmethod
    def new_profile(preset_id: str = "deepseek", name: str = DEFAULT_ASSISTANT_NAME) -> AIProfile:
        preset = preset_for(preset_id)
        return AIProfile(
            id=uuid.uuid4().hex,
            name=name,
            preset_id=preset.id,
            protocol=preset.protocol,
            base_url=preset.base_url,
            model=preset.default_model,
        )
