"""Bounded, atomic local conversation persistence for Wenzhou."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .providers import ChatMessage


SCHEMA_VERSION = 1
MAX_SESSIONS = 100
MAX_MESSAGES = 200
MAX_CONTENT_CHARACTERS = 200_000
MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_TITLE = "新对话"
_META_KEYS = {"model", "elapsed", "input_tokens", "output_tokens", "search_count"}


@dataclass
class ConversationSession:
    id: str
    title: str = DEFAULT_TITLE
    messages: list[ChatMessage] = field(default_factory=list)
    assistant_meta: list[dict[str, object]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class ConversationState:
    sessions: list[ConversationSession]
    active_session_id: str

    @property
    def active(self) -> ConversationSession:
        return next(one for one in self.sessions if one.id == self.active_session_id)


class ConversationStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.last_error = ""

    def load(self) -> ConversationState:
        self.last_error = ""
        try:
            if self.path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("对话历史超过 10 MiB 安全上限")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return self._decode(payload)
        except FileNotFoundError:
            return self.new_state()
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.last_error = f"{type(error).__name__}: {error}"
            return self.new_state()

    def save(self, state: ConversationState) -> None:
        checked = self._decode(self._encode(state))
        payload = self._encode(checked)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            if os.path.getsize(temporary) > MAX_FILE_BYTES:
                raise ValueError("对话历史超过 10 MiB 安全上限")
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def new_session(title: str = DEFAULT_TITLE) -> ConversationSession:
        return ConversationSession(uuid.uuid4().hex, _title(title))

    @classmethod
    def new_state(cls) -> ConversationState:
        session = cls.new_session()
        return ConversationState([session], session.id)

    @staticmethod
    def suggested_title(content: str) -> str:
        compact = " ".join(str(content).split())
        return compact[:30] + ("…" if len(compact) > 30 else "") or DEFAULT_TITLE

    @classmethod
    def _decode(cls, payload) -> ConversationState:
        if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
            raise ValueError("不支持的对话历史版本")
        raw_sessions = payload.get("sessions")
        if not isinstance(raw_sessions, list) or not 1 <= len(raw_sessions) <= MAX_SESSIONS:
            raise ValueError("对话数量无效")
        sessions: list[ConversationSession] = []
        ids: set[str] = set()
        for raw in raw_sessions:
            if not isinstance(raw, dict):
                raise ValueError("对话记录必须是对象")
            session_id = str(raw.get("id", "")).strip()
            if not session_id or len(session_id) > 80 or session_id in ids:
                raise ValueError("对话 ID 无效或重复")
            ids.add(session_id)
            raw_messages = raw.get("messages", [])
            if not isinstance(raw_messages, list) or len(raw_messages) > MAX_MESSAGES:
                raise ValueError("单个对话消息数量超过限制")
            messages = []
            for row in raw_messages:
                if not isinstance(row, dict) or row.get("role") not in {"user", "assistant"}:
                    raise ValueError("对话消息角色无效")
                content = str(row.get("content", ""))
                if len(content) > MAX_CONTENT_CHARACTERS:
                    raise ValueError("单条对话消息超过限制")
                messages.append(ChatMessage(row["role"], content))
            raw_meta = raw.get("assistant_meta", [])
            if not isinstance(raw_meta, list) or len(raw_meta) > MAX_MESSAGES:
                raise ValueError("对话元数据无效")
            meta = []
            for row in raw_meta:
                if not isinstance(row, dict):
                    raise ValueError("对话元数据必须是对象")
                meta.append({key: row[key] for key in _META_KEYS if key in row})
            created = _timestamp(raw.get("created_at"))
            updated = _timestamp(raw.get("updated_at"))
            sessions.append(ConversationSession(
                id=session_id,
                title=_title(raw.get("title")),
                messages=messages,
                assistant_meta=meta,
                created_at=created,
                updated_at=updated,
            ))
        active = str(payload.get("active_session_id", ""))
        if active not in ids:
            active = sessions[0].id
        return ConversationState(sessions, active)

    @staticmethod
    def _encode(state: ConversationState) -> dict:
        if not isinstance(state, ConversationState):
            raise ValueError("无效的对话状态")
        return {
            "version": SCHEMA_VERSION,
            "active_session_id": state.active_session_id,
            "sessions": [
                {
                    "id": session.id,
                    "title": session.title,
                    "messages": [
                        {"role": message.role, "content": message.content}
                        for message in session.messages
                    ],
                    "assistant_meta": [
                        {key: value for key, value in row.items() if key in _META_KEYS}
                        for row in session.assistant_meta
                    ],
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                }
                for session in state.sessions
            ],
        }


def _title(value) -> str:
    return " ".join(str(value or "").split())[:80] or DEFAULT_TITLE


def _timestamp(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = time.time()
    return parsed if 0 < parsed < 10**11 else time.time()
