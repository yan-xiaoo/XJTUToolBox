"""Model discovery and cancellable Ollama downloads."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from typing import Callable

import requests

from .providers import AIClient, AIProviderError, ProviderConfig, validate_config


@dataclass(frozen=True)
class ModelPullProgress:
    status: str
    completed: int | None = None
    total: int | None = None

    @property
    def percent(self) -> int | None:
        if not self.total or self.completed is None:
            return None
        return max(0, min(100, round(self.completed * 100 / self.total)))


class ModelOperationCancelled(RuntimeError):
    pass


def _checked_for_catalog(config: ProviderConfig) -> ProviderConfig:
    return validate_config(replace(config, model=config.model.strip() or "catalog-placeholder"))


def _response_json(response, api_key: str, max_bytes: int = 4 * 1024 * 1024):
    if not 200 <= int(response.status_code) < 300:
        raise _http_error(response, api_key)
    content = response.content
    if len(content) > max_bytes:
        raise AIProviderError("response_too_large", "模型列表响应过大")
    try:
        return response.json()
    except ValueError as error:
        raise AIProviderError("invalid_response", "模型服务返回了无效 JSON") from error


def _http_error(response, api_key: str) -> AIProviderError:
    return AIClient._http_error(response, api_key)


class ModelCatalogClient:
    def __init__(self, session: requests.Session | None = None, timeout=(10, 30)):
        self.session = session or requests.Session()
        self.timeout = timeout

    def list_models(self, config: ProviderConfig) -> list[str]:
        checked = _checked_for_catalog(config)
        headers = {"Accept": "application/json"}
        if checked.protocol == "openai":
            url = f"{checked.base_url}/models"
            headers["Authorization"] = f"Bearer {checked.api_key}"
        elif checked.protocol == "anthropic":
            url = f"{checked.base_url}/models"
            headers.update({
                "x-api-key": checked.api_key,
                "anthropic-version": "2023-06-01",
            })
        elif checked.protocol == "gemini":
            url = f"{checked.base_url}/models"
            headers["x-goog-api-key"] = checked.api_key
        else:
            url = f"{checked.base_url}/tags"
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            data = _response_json(response, checked.api_key)
        except requests.Timeout as error:
            raise AIProviderError("timeout", "获取模型列表超时") from error
        except requests.ConnectionError as error:
            raise AIProviderError("connection", "无法连接模型服务") from error
        except requests.RequestException as error:
            raise AIProviderError("network", "获取模型列表失败") from error

        if checked.protocol == "ollama":
            rows = data.get("models", []) if isinstance(data, dict) else []
            names = [row.get("name") or row.get("model") for row in rows if isinstance(row, dict)]
        else:
            rows = data.get("data", data.get("models", [])) if isinstance(data, dict) else []
            names = [row.get("id") or row.get("name") for row in rows if isinstance(row, dict)]
        normalized = []
        for name in names:
            value = str(name or "").strip()
            if checked.protocol == "gemini" and value.startswith("models/"):
                value = value[7:]
            if value and len(value) <= 200 and value not in normalized:
                normalized.append(value)
        return sorted(normalized, key=str.casefold)

    def pull_ollama_model(
        self,
        config: ProviderConfig,
        model: str,
        *,
        progress: Callable[[ModelPullProgress], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        checked = _checked_for_catalog(replace(config, model=model))
        if checked.protocol != "ollama":
            raise ValueError("只有 Ollama 协议支持把模型下载到本机")
        model = checked.model
        cancel_event = cancel_event or threading.Event()
        response = None
        try:
            response = self.session.post(
                f"{checked.base_url}/pull",
                headers={"Content-Type": "application/json"},
                json={"model": model, "stream": True},
                timeout=self.timeout,
                stream=True,
            )
            if not 200 <= int(response.status_code) < 300:
                raise _http_error(response, checked.api_key)
            for raw_line in response.iter_lines(chunk_size=64 * 1024):
                if cancel_event.is_set():
                    raise ModelOperationCancelled("模型下载已取消")
                if not raw_line:
                    continue
                if len(raw_line) > 1024 * 1024:
                    raise AIProviderError("invalid_response", "Ollama 下载进度响应过大")
                try:
                    payload = json.loads(raw_line)
                except (TypeError, ValueError) as error:
                    raise AIProviderError("invalid_response", "Ollama 返回了无效下载进度") from error
                if not isinstance(payload, dict):
                    raise AIProviderError("invalid_response", "Ollama 返回了无效下载进度")
                if payload.get("error"):
                    raise AIProviderError("pull", str(payload["error"])[:400])
                update = ModelPullProgress(
                    str(payload.get("status") or "正在下载"),
                    _optional_int(payload.get("completed")),
                    _optional_int(payload.get("total")),
                )
                if progress is not None:
                    progress(update)
            if cancel_event.is_set():
                raise ModelOperationCancelled("模型下载已取消")
        except (AIProviderError, ModelOperationCancelled):
            raise
        except requests.Timeout as error:
            if cancel_event.is_set():
                raise ModelOperationCancelled("模型下载已取消") from error
            raise AIProviderError("timeout", "模型下载超时") from error
        except requests.ConnectionError as error:
            raise AIProviderError("connection", "无法连接本机 Ollama，请先启动 Ollama") from error
        except requests.RequestException as error:
            raise AIProviderError("network", "模型下载网络请求失败") from error
        finally:
            if response is not None:
                response.close()


def _optional_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
