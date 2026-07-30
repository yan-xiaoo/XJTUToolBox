from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import requests

from notification.crawlers import crawler


NEW_CHALLENGE_HTML = """
<html>
<body>
<script>
var challengeId = 'xaBKodoB1fy8CNOAtrUmdpiGmEeTWDja';
var a = 20;
var b = 14;
var operator = '-';
var result;
</script>
</body>
</html>
"""

LEGACY_CHALLENGE_HTML = """
<html>
<body>
<script>
var challengeId = 'legacy-challenge';
var answer = 42;
</script>
</body>
</html>
"""


def make_response(
    content: str,
    status_code: int = 200,
    content_type: str = "text/html",
) -> requests.Response:
    """创建不需要联网的 requests 响应对象。"""
    response = requests.Response()
    response.status_code = status_code
    response._content = content.encode("utf-8")
    response.encoding = "utf-8"
    response.headers["Content-Type"] = content_type
    return response


class ChallengeParsingTestCase(unittest.TestCase):
    """验证新旧挑战页面的参数解析。"""

    def test_extracts_new_arithmetic_challenge(self) -> None:
        self.assertEqual(
            crawler.extract_challenge_id_from_html(NEW_CHALLENGE_HTML),
            ("xaBKodoB1fy8CNOAtrUmdpiGmEeTWDja", 6),
        )

    def test_extracts_legacy_answer(self) -> None:
        self.assertEqual(
            crawler.extract_challenge_id_from_html(LEGACY_CHALLENGE_HTML),
            ("legacy-challenge", 42),
        )

    def test_extracts_legacy_answer_from_another_script(self) -> None:
        html = """
        <script>var challengeId = "split-legacy-challenge";</script>
        <script>var answer = 7;</script>
        """
        self.assertEqual(
            crawler.extract_challenge_id_from_html(html),
            ("split-legacy-challenge", 7),
        )

    def test_returns_challenge_id_when_expression_is_unknown(self) -> None:
        html = """
        <script>
        var challengeId = "unknown-challenge";
        var result = calculateAnswer();
        </script>
        """
        self.assertEqual(
            crawler.extract_challenge_id_from_html(html),
            ("unknown-challenge", None),
        )


class JavaScriptSimpleHashTestCase(unittest.TestCase):
    """验证 Python 哈希与页面中的 JavaScript 行为一致。"""

    def test_matches_known_node_results(self) -> None:
        cases = {
            "": 0,
            "xaBKodoB1fy8CNOAtrUmdpiGmEeTWDja6Mozilla/5.": 2006031112,
            "polygenelubricants": 2147483648,
            "中文验证": 622446895,
            "emoji🙂test🚀": 1156788704,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(crawler.javascript_simple_hash(value), expected)


class PassChallengeTestCase(unittest.TestCase):
    """验证挑战请求会按照页面版本构造。"""

    website_url = "https://example.edu.cn/notice.htm"
    challenge_url = "https://example.edu.cn/dynamic_challenge"
    user_agent = "Mozilla/5.0 Test Browser"

    def make_session(
        self,
        initial_response: requests.Response,
        challenge_response: requests.Response,
    ) -> tuple[requests.Session, Mock]:
        """创建带有模拟 GET 和 POST 请求的 session。"""
        session = requests.Session()
        session.headers["User-Agent"] = self.user_agent
        session.get = Mock(return_value=initial_response)
        post = Mock(return_value=challenge_response)
        session.post = post
        return session, post

    def test_posts_new_payload_with_hash(self) -> None:
        initial_response = make_response(NEW_CHALLENGE_HTML)
        challenge_response = make_response(
            json.dumps({"success": True, "client_id": "new-client"}),
            content_type="application/json",
        )
        session, post = self.make_session(initial_response, challenge_response)

        with (
            patch.object(crawler, "get_session", return_value=session),
            patch.object(crawler, "get_client_id", return_value=None),
            patch.object(crawler, "set_client_id") as set_client_id,
        ):
            result = crawler.pass_challenge_for_website(
                self.website_url,
                self.challenge_url,
            )

        self.assertIs(result, session)
        request_data = post.call_args.kwargs["json"]
        self.assertEqual(request_data["answer"], 6)
        self.assertEqual(
            request_data["hash"],
            crawler.javascript_simple_hash(
                "xaBKodoB1fy8CNOAtrUmdpiGmEeTWDja6Mozilla/5.",
            ),
        )
        self.assertEqual(
            request_data["browser_info"],
            {
                "userAgent": self.user_agent,
                "language": "zh-CN",
                "platform": crawler.get_system_platform(),
                "screen": {
                    "width": 1920,
                    "height": 1080,
                    "colorDepth": 24,
                },
                "timezoneOffset": -480,
                "hasTouchEvents": False,
            },
        )
        self.assertEqual(
            crawler.get_cookie_value(
                session.cookies,
                "client_id",
                "example.edu.cn",
            ),
            "new-client",
        )
        set_client_id.assert_called_once_with(self.website_url, "new-client")

    def test_keeps_legacy_payload_compatible(self) -> None:
        initial_response = make_response(LEGACY_CHALLENGE_HTML)
        challenge_response = make_response(
            json.dumps({"client_id": "legacy-client"}),
            content_type="application/json",
        )
        session, post = self.make_session(initial_response, challenge_response)

        with (
            patch.object(crawler, "get_session", return_value=session),
            patch.object(crawler, "get_client_id", return_value=None),
            patch.object(crawler, "set_client_id"),
        ):
            crawler.pass_challenge_for_website(
                self.website_url,
                self.challenge_url,
            )

        request_data = post.call_args.kwargs["json"]
        self.assertNotIn("hash", request_data)
        self.assertEqual(request_data["answer"], 42)
        self.assertEqual(
            set(request_data["browser_info"]),
            {
                "cookieEnabled",
                "deviceMemory",
                "hardwareConcurrency",
                "language",
                "platform",
                "timezone",
                "userAgent",
            },
        )

    def test_rejects_unsuccessful_response(self) -> None:
        initial_response = make_response(NEW_CHALLENGE_HTML)
        challenge_response = make_response(
            json.dumps({"success": False}),
            content_type="application/json",
        )
        session, _ = self.make_session(initial_response, challenge_response)

        with (
            patch.object(crawler, "get_session", return_value=session),
            patch.object(crawler, "get_client_id", return_value=None),
            self.assertRaisesRegex(ValueError, "网站拒绝了人机验证"),
        ):
            crawler.pass_challenge_for_website(
                self.website_url,
                self.challenge_url,
            )


if __name__ == "__main__":
    unittest.main()
