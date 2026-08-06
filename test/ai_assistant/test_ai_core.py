import json
import tempfile
import unittest
from pathlib import Path

import requests

from ai_assistant import (
    AIClient,
    AIConfigStore,
    AIProfile,
    AIProviderError,
    ChatMessage,
    ProviderConfig,
    SecretPersistence,
    ToolCall,
    ToolDefinition,
)
from app.search import fuzzy_score, normalize_search_text, rank_items


MESSAGES = [
    ChatMessage("system", "Be precise"),
    ChatMessage("user", "hello"),
]
TOOLS = [ToolDefinition(
    "lookup_notice",
    "Look up a public notice",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)]
TOOL_ROUND_TRIP = [
    ChatMessage("system", "Be precise"),
    ChatMessage("user", "find a notice"),
    ChatMessage("assistant", tool_calls=(ToolCall("call-1", "lookup_notice", {"query": "考试"}),)),
    ChatMessage("tool", "one result", tool_call_id="call-1"),
]


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self.payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class ProviderAdapterTest(unittest.TestCase):
    def test_openai_compatible_request_and_response(self):
        session = FakeSession(FakeResponse({
            "model": "test-model",
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }))
        result = AIClient(session).complete(
            MESSAGES,
            ProviderConfig("openai", "https://example.test/v1", "test-model", "secret"),
        )
        url, request = session.calls[0]
        self.assertEqual(url, "https://example.test/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(request["json"]["messages"][1]["content"], "hello")
        self.assertEqual((result.text, result.input_tokens, result.output_tokens), ("answer", 2, 3))

    def test_native_anthropic_request_and_response(self):
        session = FakeSession(FakeResponse({
            "model": "claude-test",
            "content": [{"type": "text", "text": "anthropic answer"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 4, "output_tokens": 5},
        }))
        result = AIClient(session).complete(
            MESSAGES,
            ProviderConfig("anthropic", "https://api.anthropic.test/v1", "claude-test", "secret"),
        )
        url, request = session.calls[0]
        self.assertEqual(url, "https://api.anthropic.test/v1/messages")
        self.assertEqual(request["headers"]["x-api-key"], "secret")
        self.assertEqual(request["json"]["system"], "Be precise")
        self.assertEqual(request["json"]["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(result.text, "anthropic answer")

    def test_openai_and_anthropic_map_tool_round_trip_natively(self):
        openai_session = FakeSession(FakeResponse({
            "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
        }))
        AIClient(openai_session).complete(
            TOOL_ROUND_TRIP,
            ProviderConfig("openai", "https://openai.test/v1", "model", "secret"),
            TOOLS,
        )
        openai_body = openai_session.calls[0][1]["json"]
        self.assertEqual(openai_body["tools"][0]["function"]["parameters"]["type"], "object")
        self.assertEqual(openai_body["messages"][0], {"role": "system", "content": "Be precise"})
        self.assertEqual(openai_body["messages"][2]["tool_calls"][0]["function"]["name"], "lookup_notice")
        self.assertEqual(openai_body["messages"][3]["role"], "tool")
        self.assertEqual(openai_body["messages"][3]["tool_call_id"], "call-1")

        anthropic_session = FakeSession(FakeResponse({
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
        }))
        AIClient(anthropic_session).complete(
            TOOL_ROUND_TRIP,
            ProviderConfig("anthropic", "https://anthropic.test/v1", "model", "secret"),
            TOOLS,
        )
        anthropic_body = anthropic_session.calls[0][1]["json"]
        self.assertEqual(anthropic_body["system"], "Be precise")
        self.assertNotIn("system", [message["role"] for message in anthropic_body["messages"]])
        self.assertEqual(anthropic_body["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual(anthropic_body["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(anthropic_body["messages"][2]["content"][0], {
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": "one result",
        })

    def test_protocol_tool_responses_are_normalized(self):
        openai = FakeSession(FakeResponse({
            "choices": [{"message": {"content": None, "tool_calls": [{
                "id": "openai-call",
                "type": "function",
                "function": {"name": "lookup_notice", "arguments": "{\"query\":\"考试\"}"},
            }]}, "finish_reason": "tool_calls"}],
        }))
        result = AIClient(openai).complete(
            MESSAGES,
            ProviderConfig("openai", "https://openai.test/v1", "model", "secret"),
            TOOLS,
        )
        self.assertEqual(result.tool_calls[0].arguments, {"query": "考试"})

        anthropic = FakeSession(FakeResponse({
            "content": [{
                "type": "tool_use", "id": "anthropic-call", "name": "lookup_notice",
                "input": {"query": "培养"},
            }],
            "stop_reason": "tool_use",
        }))
        result = AIClient(anthropic).complete(
            MESSAGES,
            ProviderConfig("anthropic", "https://anthropic.test/v1", "model", "secret"),
            TOOLS,
        )
        self.assertEqual(result.tool_calls[0].arguments, {"query": "培养"})

    def test_native_gemini_request_and_response(self):
        session = FakeSession(FakeResponse({
            "candidates": [{
                "content": {"parts": [{"text": "gemini answer"}]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 7},
        }))
        result = AIClient(session).complete(
            MESSAGES,
            ProviderConfig("gemini", "https://gemini.test/v1beta", "gemini-test", "a key"),
        )
        url, request = session.calls[0]
        self.assertIn("/models/gemini-test:generateContent", url)
        self.assertNotIn("a%20key", url)
        self.assertEqual(request["headers"]["x-goog-api-key"], "a key")
        self.assertEqual(request["json"]["systemInstruction"]["parts"][0]["text"], "Be precise")
        self.assertEqual(result.text, "gemini answer")

    def test_native_ollama_allows_loopback_without_key(self):
        session = FakeSession(FakeResponse({
            "model": "qwen3:8b",
            "message": {"content": "local answer"},
            "done_reason": "stop",
        }))
        result = AIClient(session).complete(
            MESSAGES,
            ProviderConfig("ollama", "http://127.0.0.1:11434/api", "qwen3:8b"),
        )
        self.assertEqual(session.calls[0][0], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(result.text, "local answer")

    def test_network_and_http_edges_have_stable_safe_errors(self):
        cases = [
            (FakeSession(error=requests.Timeout()), "timeout"),
            (FakeSession(FakeResponse({"error": {"message": "bad secret"}}, 401)), "authentication"),
            (FakeSession(FakeResponse({"error": "slow down"}, 429)), "rate_limit"),
            (FakeSession(FakeResponse({}, 503)), "upstream"),
            (FakeSession(FakeResponse(ValueError("bad json"))), "invalid_response"),
            (FakeSession(FakeResponse({"choices": [{"message": {"content": ""}}]})), "empty_response"),
        ]
        for session, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(AIProviderError) as raised:
                    AIClient(session).complete(
                        MESSAGES,
                        ProviderConfig("openai", "https://example.test/v1", "model", "secret"),
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("bad secret", str(raised.exception))

    def test_validation_rejects_empty_and_insecure_remote_requests(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            AIClient(FakeSession()).complete(
                MESSAGES,
                ProviderConfig("openai", "http://example.test/v1", "model", "secret"),
            )
        with self.assertRaisesRegex(ValueError, "API Key"):
            AIClient(FakeSession()).complete(
                MESSAGES,
                ProviderConfig("anthropic", "https://example.test/v1", "model", ""),
            )
        with self.assertRaisesRegex(ValueError, "查询参数"):
            AIClient(FakeSession()).complete(
                MESSAGES,
                ProviderConfig("openai", "https://example.test/v1?key=leak", "model", "secret"),
            )
        with self.assertRaisesRegex(ValueError, "至少"):
            AIClient(FakeSession()).complete(
                [ChatMessage("system", "only system")],
                ProviderConfig("openai", "https://example.test/v1", "model", "secret"),
            )
        with self.assertRaisesRegex(ValueError, "tool_call_id"):
            AIClient(FakeSession()).complete(
                [ChatMessage("user", "hello"), ChatMessage("tool", "result")],
                ProviderConfig("openai", "https://example.test/v1", "model", "secret"),
            )
        with self.assertRaisesRegex(ValueError, "尚未启用工具调用"):
            AIClient(FakeSession()).complete(
                MESSAGES,
                ProviderConfig("gemini", "https://example.test/v1", "model", "secret"),
                TOOLS,
            )


class FakeKeyring:
    def __init__(self, fail=False):
        self.fail = fail
        self.values = {}

    def set_password(self, service, name, value):
        if self.fail:
            raise RuntimeError("no backend")
        self.values[(service, name)] = value

    def get_password(self, service, name):
        if self.fail:
            raise RuntimeError("no backend")
        return self.values.get((service, name))

    def delete_password(self, service, name):
        self.values.pop((service, name), None)


class ConfigSecurityTest(unittest.TestCase):
    def test_api_key_never_appears_in_metadata_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = AIConfigStore(path, FakeKeyring())
            profile = AIProfile.default()
            store.save_profiles([profile])
            persistence = store.set_secret(profile.id, "top-secret-value")

            self.assertEqual(persistence, SecretPersistence.KEYRING)
            self.assertEqual(store.get_secret(profile.id), "top-secret-value")
            self.assertNotIn("top-secret-value", path.read_text(encoding="utf-8"))

    def test_missing_keyring_uses_session_memory_not_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = AIConfigStore(path, FakeKeyring(fail=True))
            profile = AIProfile.default()
            store.save_profiles([profile])
            persistence = store.set_secret(profile.id, "session-only-secret")

            self.assertEqual(persistence, SecretPersistence.SESSION)
            self.assertEqual(store.get_secret(profile.id), "session-only-secret")
            self.assertNotIn("session-only-secret", path.read_text(encoding="utf-8"))

    def test_corrupt_profile_file_falls_back_without_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text("{broken", encoding="utf-8")
            store = AIConfigStore(path, FakeKeyring())
            profiles = store.load_profiles()
            self.assertEqual(profiles, [AIProfile.default()])
            self.assertTrue(store.last_error)

    def test_legacy_default_brand_is_migrated_without_overwriting_custom_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            legacy = {
                **AIProfile.default().__dict__,
                "name": "屁岱",
                "system_prompt": "你是仙交百宝箱中的 AI 助手屁岱。请准确、坦诚地回答，不确定时明确说明。",
            }
            path.write_text(
                json.dumps({"version": 1, "profiles": [legacy]}, ensure_ascii=False),
                encoding="utf-8",
            )
            profile = AIConfigStore(path, FakeKeyring()).load_profiles()[0]
            self.assertEqual(profile.name, "问舟")
            self.assertIn("助手问舟", profile.system_prompt)

            legacy["system_prompt"] = "我的自定义提示词"
            path.write_text(
                json.dumps({"version": 1, "profiles": [legacy]}, ensure_ascii=False),
                encoding="utf-8",
            )
            profile = AIConfigStore(path, FakeKeyring()).load_profiles()[0]
            self.assertEqual(profile.name, "问舟")
            self.assertEqual(profile.system_prompt, "我的自定义提示词")


class SearchQualityTest(unittest.TestCase):
    def test_normalization_and_chinese_subsequence(self):
        self.assertEqual(normalize_search_text("ＡＩ　通知").spaced, "ai 通知")
        self.assertIsNotNone(fuzzy_score("电气研究生", ["电气工程学院", "研究生通知"]))
        self.assertIsNotNone(fuzzy_score("医学 值班", ["医学部机关2026年暑假值班表"]))
        self.assertIsNone(fuzzy_score("完全无关关键词", ["电气工程学院"]))

    def test_ranking_is_stable_and_scales_to_large_lists(self):
        items = ["电气通知", "电气学院研究生通知", "机械通知"]
        ranked = rank_items(items, "电气通知", lambda item: [item])
        self.assertEqual(ranked[:2], items[:2])
        large = [f"学院通知 {index}" for index in range(5000)]
        result = rank_items(large, "4999", lambda item: [item])
        self.assertEqual(result[0], "学院通知 4999")
        self.assertEqual(rank_items(items, "", lambda item: [item]), items)


if __name__ == "__main__":
    unittest.main()
