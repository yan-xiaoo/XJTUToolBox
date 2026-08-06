import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from ai_assistant.capabilities import collect_local_context
from ai_assistant.config import AIConfigStore, AIProfile, SCHEMA_VERSION, validate_profile
from ai_assistant.conversations import ConversationStore, MAX_CONTENT_CHARACTERS
from ai_assistant.markdown_render import render_markdown_fragment
from ai_assistant.model_catalog import ModelCatalogClient, ModelOperationCancelled
from ai_assistant.providers import PRESETS, ProviderConfig, validate_config
from ai_assistant.web_search import (
    SearchHumanVerificationRequired,
    WebSearchClient,
    validate_search_settings,
)
from ai_assistant import ChatMessage
from score_statistics import calculate_score_statistics


class FakeResponse:
    def __init__(self, payload=None, *, status=200, text="", url="https://example.test/"):
        self.payload = payload
        self.status_code = status
        self.text = text
        self.content = text.encode() if text else json.dumps(payload or {}).encode()
        self.url = url
        self.closed = False
        self.encoding = "utf-8"

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def iter_lines(self, **_kwargs):
        for row in self.payload or []:
            yield json.dumps(row).encode()

    def iter_content(self, **_kwargs):
        yield self.content

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if isinstance(self.get_response, Exception):
            raise self.get_response
        return self.get_response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.post_response


class IndependentProtocolConfigTest(unittest.TestCase):
    def test_provider_preset_is_only_a_quick_configuration(self):
        profile = replace(
            AIProfile.default(),
            protocol="anthropic",
            base_url="https://gateway.example/v1",
            model="custom-claude",
        )
        checked = validate_profile(profile)
        self.assertEqual(checked.preset_id, "deepseek")
        self.assertEqual(checked.protocol, "anthropic")

    def test_v1_profile_migrates_to_default_off_capabilities_and_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            profile = AIProfile.default()
            legacy = {key: value for key, value in profile.__dict__.items() if key not in {
                "capability_ids", "search_engine", "search_endpoint", "search_result_limit"
            }}
            path.write_text(json.dumps({"version": 1, "profiles": [legacy]}), encoding="utf-8")
            store = AIConfigStore(path, keyring_backend=object())
            loaded = store.load_profiles()[0]
            self.assertEqual(loaded.capability_ids, ())
            store.save_profiles([loaded])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], SCHEMA_VERSION)

    def test_retired_deepseek_models_are_migrated_and_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            legacy = replace(AIProfile.default(), model="deepseek-chat")
            path.write_text(
                json.dumps({"version": SCHEMA_VERSION, "profiles": [legacy.__dict__]}),
                encoding="utf-8",
            )
            loaded = AIConfigStore(path, keyring_backend=object()).load_profiles()[0]

        self.assertEqual(loaded.model, "deepseek-v4-flash")
        self.assertTrue(all(preset.default_model != "deepseek-chat" for preset in PRESETS))
        with self.assertRaisesRegex(ValueError, "已停用"):
            validate_config(ProviderConfig(
                "openai",
                "https://api.deepseek.com/v1",
                "deepseek-chat",
                "secret",
            ))


class ModelCatalogTest(unittest.TestCase):
    def test_lists_ollama_models_and_uses_official_tags_endpoint(self):
        response = FakeResponse({"models": [{"name": "qwen3:8b"}, {"model": "gemma3"}]})
        session = FakeSession(get_response=response)
        models = ModelCatalogClient(session).list_models(
            ProviderConfig("ollama", "http://127.0.0.1:11434/api", "unused")
        )
        self.assertEqual(models, ["gemma3", "qwen3:8b"])
        self.assertEqual(session.calls[0][1], "http://127.0.0.1:11434/api/tags")

    def test_pull_reports_progress_closes_response_and_can_cancel(self):
        response = FakeResponse([
            {"status": "pulling", "completed": 5, "total": 10},
            {"status": "success", "completed": 10, "total": 10},
        ])
        session = FakeSession(post_response=response)
        progress = []
        ModelCatalogClient(session).pull_ollama_model(
            ProviderConfig("ollama", "http://127.0.0.1:11434/api", "qwen3:8b"),
            "qwen3:8b",
            progress=progress.append,
        )
        self.assertEqual([one.percent for one in progress], [50, 100])
        self.assertTrue(response.closed)
        self.assertEqual(session.calls[0][2]["json"], {"model": "qwen3:8b", "stream": True})

        cancel = threading.Event()
        cancel.set()
        canceled_response = FakeResponse([{"status": "pulling"}])
        with self.assertRaises(ModelOperationCancelled):
            ModelCatalogClient(FakeSession(post_response=canceled_response)).pull_ollama_model(
                ProviderConfig("ollama", "http://localhost:11434/api", "qwen3:8b"),
                "qwen3:8b",
                cancel_event=cancel,
            )
        self.assertTrue(canceled_response.closed)

    def test_remote_protocol_cannot_download(self):
        with self.assertRaisesRegex(ValueError, "Ollama"):
            ModelCatalogClient(FakeSession()).pull_ollama_model(
                ProviderConfig("openai", "https://example.test/v1", "model", "key"),
                "model",
            )


class WebSearchTest(unittest.TestCase):
    def test_custom_searxng_is_bounded_and_parsed(self):
        response = FakeResponse(
            {"results": [
                {"title": "Result", "url": "https://source.test/a", "content": "Snippet"},
                {"title": "Bad", "url": "javascript:alert(1)", "content": "x"},
            ]},
            url="https://search.example/search?q=x&format=json",
        )
        session = FakeSession(get_response=response)
        results = WebSearchClient(session).search(
            "x", engine="searxng", endpoint="https://search.example", limit=5
        )
        self.assertEqual([(one.title, one.url) for one in results], [("Result", "https://source.test/a")])
        self.assertEqual(session.calls[0][1], "https://search.example/search")
        self.assertFalse(session.calls[0][2]["allow_redirects"])
        self.assertTrue(session.calls[0][2]["stream"])
        self.assertTrue(response.closed)

    def test_rejects_credentials_insecure_remote_and_cross_host_redirect(self):
        invalid = [
            "http://remote.example/search",
            "https://user:secret@search.example/search",
            "https://search.example/search?q=preset",
        ]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_search_settings("searxng", endpoint)
        response = FakeResponse({"results": []}, url="https://evil.example/search")
        with self.assertRaisesRegex(RuntimeError, "未配置"):
            WebSearchClient(FakeSession(get_response=response)).search(
                "x", engine="searxng", endpoint="https://search.example"
            )

    def test_timeout_redirect_and_oversized_stream_are_safe(self):
        import requests

        with self.assertRaisesRegex(RuntimeError, "超时"):
            WebSearchClient(FakeSession(get_response=requests.Timeout())).search(
                "x", engine="searxng", endpoint="https://search.example"
            )
        redirect = FakeResponse({}, status=302, url="https://search.example/search")
        with self.assertRaisesRegex(RuntimeError, "重定向"):
            WebSearchClient(FakeSession(get_response=redirect)).search(
                "x", engine="searxng", endpoint="https://search.example"
            )
        oversized = FakeResponse({}, url="https://search.example/search")
        oversized.content = b"x" * (2 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(RuntimeError, "2 MiB"):
            WebSearchClient(FakeSession(get_response=oversized)).search(
                "x", engine="searxng", endpoint="https://search.example"
            )
        self.assertTrue(oversized.closed)

    def test_duckduckgo_human_challenge_is_not_misreported_as_empty_results(self):
        challenged = FakeResponse(
            text='<html><form id="challenge-form"><div class="anomaly-modal">captcha</div></form></html>',
            url="https://html.duckduckgo.com/html/",
        )
        with self.assertRaisesRegex(SearchHumanVerificationRequired, "人机验证"):
            WebSearchClient(FakeSession(get_response=challenged)).search(
                "x", engine="duckduckgo", endpoint="https://ignored.example", limit=3
            )
        self.assertTrue(challenged.closed)

    def test_mainstream_engines_use_configured_searxng_and_explicit_engine(self):
        for engine in ("bing", "baidu", "google"):
            response = FakeResponse(
                {"results": [{"title": engine, "url": f"https://{engine}.example/result"}]},
                url="https://search.example/search",
            )
            session = FakeSession(get_response=response)
            results = WebSearchClient(session).search(
                "x", engine=engine, endpoint="https://search.example", limit=3
            )
            self.assertEqual(results[0].title, engine)
            call = session.calls[0]
            self.assertEqual(call[1], "https://search.example/search")
            self.assertEqual(call[2]["params"]["engines"], engine)
            self.assertEqual(call[2]["params"]["format"], "json")


class CapabilityAndMarkdownTest(unittest.TestCase):
    def test_only_explicit_local_capabilities_are_included_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notice = root / "notification.json"
            notice.write_text(json.dumps([{
                "title": "公开通知", "date": "2026-08-04", "source": "dean/jxtz",
                "link": "https://example.test/private?token=secret",
            }]), encoding="utf-8")
            (root / "score.json").write_text(json.dumps({"scores": [{
                "courseName": "高等数学", "score": 95, "coursePoint": 5, "gpa": 4.1,
                "studentId": "sensitive-id",
            }]}), encoding="utf-8")
            context = collect_local_context(
                ("public_notices",), notification_path=notice, account_directory=root
            )
            self.assertIn("公开通知", context.text)
            self.assertNotIn("高等数学", context.text)
            self.assertNotIn("token=", context.text)

            score_context = collect_local_context(("scores",), account_directory=root)
            self.assertIn("高等数学", score_context.text)
            self.assertNotIn("sensitive-id", score_context.text)

    def test_schedule_database_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE courseinstance (name, day_of_week, start_time, end_time, week_number, location, teacher)"
            )
            connection.execute(
                "INSERT INTO courseinstance VALUES ('线性代数', 1, 1, 2, 3, '主楼', '张老师')"
            )
            connection.commit()
            connection.close()
            context = collect_local_context(("schedule",), account_directory=directory)
            self.assertIn("线性代数", context.text)
            self.assertIn("主楼", context.text)

    def test_all_real_cache_shapes_share_the_budget_and_reach_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notice = root / "notification.json"
            notice.write_text(json.dumps([{
                "title": "创新竞赛通知", "date": "2026-08-05", "source": "dean/jxtz",
                "link": "https://secret.invalid/?token=not-sent",
            }]), encoding="utf-8")
            (root / "score.json").write_text(json.dumps({"scores": [
                {"courseName": "高等数学", "score": 90, "coursePoint": 4, "gpa": 4.0,
                 "studentId": "must-not-reach-provider"},
                {"courseName": "大学物理", "score": 80, "coursePoint": 2, "gpa": 3.0},
            ]}), encoding="utf-8")
            (root / "attendance_flow.json").write_text(json.dumps([{
                "sBh": "private-record-id", "eqno": "主楼A101",
                "watertime": "2026-08-05 08:01:00", "isdone": 1,
            }]), encoding="utf-8")
            connection = sqlite3.connect(root / "schedule.db")
            connection.execute(
                "CREATE TABLE courseinstance (name, day_of_week, start_time, end_time, week_number, location, teacher)"
            )
            connection.execute(
                "INSERT INTO courseinstance VALUES ('线性代数', 2, 3, 4, 1, '西一楼', '李老师')"
            )
            connection.commit()
            connection.close()

            context = collect_local_context(
                ("public_notices", "schedule", "scores", "attendance"),
                notification_path=notice,
                account_directory=root,
                max_characters=2400,
            )
            for heading in ("公开通知", "我的课表", "我的成绩", "我的考勤"):
                self.assertIn(f"## {heading}", context.text)
            for value in ("创新竞赛通知", "线性代数", "高等数学", "主楼A101"):
                self.assertIn(value, context.text)
            self.assertIn("成绩页统计", context.text)
            self.assertIn("86.667", context.text)
            self.assertNotIn("token=", context.text)
            self.assertNotIn("must-not-reach-provider", context.text)
            self.assertNotIn("private-record-id", context.text)
            self.assertEqual(set(context.included), {"public_notices", "schedule", "scores", "attendance"})
            self.assertFalse(context.unavailable)

    def test_markdown_renders_structure_but_removes_active_content(self):
        rendered = render_markdown_fragment(
            "# 标题\n\n**粗体** [安全](https://example.test) "
            "[危险](javascript:alert(1)) <script>alert(1)</script> ![跟踪](https://evil.test/x.png)"
        )
        self.assertIn("<h1>标题</h1>", rendered)
        self.assertIn("<strong>粗体</strong>", rendered)
        self.assertIn('href="https://example.test"', rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<img", rendered)

    def test_code_characters_highlight_once_and_user_styles_remain_untrusted(self):
        rendered = render_markdown_fragment(
            "```cpp\n#include <iostream>\nif (a < b && b > 0) return 1;\n```"
        )
        self.assertIn("&lt;iostream&gt;", rendered)
        self.assertNotIn("&amp;lt;iostream", rendered)
        self.assertIn("<span style=", rendered)
        entity = render_markdown_fragment("```cpp\n#include &lt;iostream&gt;\n```")
        self.assertIn("&lt;iostream&gt;", entity)
        self.assertNotIn("&amp;lt;iostream", entity)

        hostile = render_markdown_fragment(
            '<script>alert(1)</script>x '
            '<span class="x\\" onload=alert(1)" style="color:red" onclick="bad()">safe</span> '
            '![pixel](https://evil.test/a.png) [bad](javascript:alert(1))'
        )
        self.assertNotIn("script", hostile.lower())
        self.assertNotIn("onload", hostile.lower())
        self.assertNotIn("onclick", hostile.lower())
        self.assertNotIn("style=", hostile.lower())
        self.assertNotIn("<img", hostile.lower())
        self.assertNotIn("javascript:", hostile.lower())

    def test_unknown_and_oversized_code_fall_back_safely(self):
        unknown = render_markdown_fragment("```not-a-real-language\n<a & b>\n```")
        self.assertIn("&lt;a &amp; b&gt;", unknown)
        oversized = render_markdown_fragment(
            "```python\n" + "x < y & z\n" * 12000 + "```"
        )
        self.assertNotIn("<span style=", oversized)
        self.assertIn("x &lt; y &amp; z", oversized)


class SharedScoreStatisticsTest(unittest.TestCase):
    def test_score_page_and_wenzhou_share_one_weighted_result(self):
        result = calculate_score_statistics([
            {"coursePoint": 4, "score": 90, "gpa": 4.0},
            {"coursePoint": 2, "score": 80, "gpa": 3.0},
            {"coursePoint": 1, "score": "A", "gpa": None},
        ])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.weighted_average, 86.666666, places=5)
        self.assertAlmostEqual(result.weighted_gpa, 3.666666, places=5)
        self.assertEqual(result.incomplete_count, 1)


class ConversationStoreTest(unittest.TestCase):
    def test_atomic_round_trip_active_session_and_corruption_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversations.json"
            store = ConversationStore(path)
            state = store.new_state()
            first = state.active
            first.title = "第一段"
            first.messages.extend([ChatMessage("user", "问题"), ChatMessage("assistant", "回答")])
            first.assistant_meta.append({"model": "fixture", "secret": "drop-me"})
            second = store.new_session("第二段")
            state.sessions.append(second)
            state.active_session_id = second.id
            store.save(state)
            loaded = store.load()
            self.assertEqual(loaded.active.title, "第二段")
            self.assertEqual(loaded.sessions[0].messages[-1].content, "回答")
            self.assertNotIn("secret", loaded.sessions[0].assistant_meta[0])
            self.assertFalse(any(path.parent.glob(f".{path.name}.*.tmp")))

            path.write_text("{broken", encoding="utf-8")
            fallback = store.load()
            self.assertEqual(len(fallback.sessions), 1)
            self.assertTrue(store.last_error)

    def test_rejects_oversized_single_message(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "conversations.json")
            state = store.new_state()
            state.active.messages.append(ChatMessage("user", "x" * (MAX_CONTENT_CHARACTERS + 1)))
            with self.assertRaisesRegex(ValueError, "超过限制"):
                store.save(state)


if __name__ == "__main__":
    unittest.main()
