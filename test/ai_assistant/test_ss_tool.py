import os
import unittest
from unittest.mock import Mock

TEST_DOMAIN = "ai"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ai_assistant import ChatMessage, ProviderConfig, ToolCall
from ai_assistant.capabilities import collect_local_context
from ai_assistant.providers import ChatResult
from ai_assistant.ss_tool import make_activity_runner, run_activity
from ss.activity import ActivityDetail

OPEN_DETAIL = {
    "HDDM": "A1", "HDMC": "保研分享会", "SFXYBM": "1", "BMFS": "1", "HASAPPLY": "0",
    "BMKSSJ": "2000-01-01 00:00", "BMJSSJ": "2999-01-01 00:00",
}


class ActivityToolTest(unittest.TestCase):
    def test_apply_refuses_when_window_closed_without_calling_server(self):
        api = Mock()
        api.detail.return_value = ActivityDetail.from_row({**OPEN_DETAIL, "BMJSSJ": "2001-01-01 00:00"})
        reply = run_activity(api, {"action": "apply", "id": "A1"})
        self.assertIn("已截止", reply)
        api.apply.assert_not_called()

    def test_apply_goes_through_when_open(self):
        api = Mock()
        api.detail.return_value = ActivityDetail.from_row(OPEN_DETAIL)
        self.assertIn("已报名", run_activity(api, {"action": "apply", "id": "A1"}))
        api.apply.assert_called_once_with("A1")

    def test_runner_reports_login_failure_as_text(self):
        def factory():
            raise RuntimeError("还没有添加账户")
        run = make_activity_runner(factory)
        self.assertIn("还没有添加账户", run(ToolCall("c1", "activity", {"action": "mine"})))

    def test_tool_capability_reads_no_local_cache(self):
        context = collect_local_context(["ss_activity"])
        self.assertEqual((context.text, context.unavailable), ("", ()))


class ToolLoopTest(unittest.TestCase):
    def test_thread_feeds_tool_results_back_until_text_answer(self):
        from app.AIInterface import _AIRequestThread

        calls = (ToolCall("c1", "activity", {"action": "group_proof"}),)
        client = Mock()
        client.complete.side_effect = [
            ChatResult("", "m", tool_calls=calls),
            ChatResult("找到 1 个讲座", "m"),
        ]
        runner = Mock(return_value="id A1｜高数讲座")
        thread = _AIRequestThread(
            [ChatMessage("user", "我要集体活动证明")],
            ProviderConfig("openai", "https://api.example.com/v1", "m"),
            tool_runner=runner,
        )
        thread.ai_client = client
        messages = [ChatMessage("user", "我要集体活动证明")]
        result = thread._complete(messages)
        self.assertEqual(result.text, "找到 1 个讲座")
        runner.assert_called_once_with(calls[0])
        self.assertEqual([m.role for m in messages], ["user", "assistant", "tool"])
        self.assertEqual(messages[-1].tool_call_id, "c1")
        self.assertEqual(client.complete.call_args.kwargs["tools"][0].name, "activity")

    def test_thread_without_tools_keeps_two_argument_call(self):
        from app.AIInterface import _AIRequestThread

        client = Mock()
        client.complete.return_value = ChatResult("你好", "m")
        thread = _AIRequestThread([ChatMessage("user", "hi")], ProviderConfig("openai", "https://api.example.com/v1", "m"))
        thread.ai_client = client
        self.assertEqual(thread._complete([ChatMessage("user", "hi")]).text, "你好")
        self.assertEqual(len(client.complete.call_args.args), 2)
        self.assertEqual(client.complete.call_args.kwargs, {})


if __name__ == "__main__":
    unittest.main()
