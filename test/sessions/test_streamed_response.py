import unittest
from unittest.mock import Mock

from app.sessions.common_session import LoginContext
from app.sessions.lms_session import LMSSession
from auth import ServerError

TEST_DOMAIN = "auth-session"
TEST_REGRESSION = True


class _FakeDownloadResponse:
    """模拟思源学堂回放视频那种大响应：没有 Content-Type，长度近 1 GB"""

    def __init__(self, headers: dict, text: str = "") -> None:
        self.headers = headers
        self._text = text
        self.text_reads = 0
        self.raw = None

    @property
    def text(self) -> str:
        self.text_reads += 1
        return self._text


class StreamedResponseAuthCheckTest(unittest.TestCase):
    """
    回归：流式下载的响应不能被登录页判定整个读进内存。
    这条判定以前会无条件读 response.text —— 954 MB 的回放视频因此被整个缓冲，
    下载线程一直停在 0%，内存涨到 1 GB。
    """

    def _session_with(self, response) -> LMSSession:
        session = LMSSession()
        session.backend.session.request = Mock(return_value=response)
        self.addCleanup(session.close)
        return session

    def test_streamed_download_does_not_read_body(self):
        for content_type in (None, "application/octet-stream", "video/mp4"):
            with self.subTest(content_type=content_type):
                headers = {"Content-Length": str(954 * 1024 * 1024)}
                if content_type is not None:
                    headers["Content-Type"] = content_type
                response = _FakeDownloadResponse(headers)
                session = self._session_with(response)

                got = session.request("GET", "https://example.com/video.mp4", stream=True)

                self.assertIs(got, response)
                self.assertEqual(response.text_reads, 0)

    def test_streamed_login_page_retries_without_reading_download_body(self):
        for content_type in ("text/html; charset=utf-8", "text/plain", "application/xhtml+xml"):
            with self.subTest(content_type=content_type):
                login_page = _FakeDownloadResponse(
                    {"Content-Type": content_type},
                    '<form id="fm1"><input name="execution">统一身份认证</form>',
                )
                download = _FakeDownloadResponse({"Content-Length": str(954 * 1024 * 1024)})
                session = self._session_with(login_page)
                session.backend.session.request.side_effect = [login_page, download]
                session._login_context = LoginContext("user", "password", None, False, {})
                session._ensure_login_context_matches_current_account = Mock()
                session.ensure_login = Mock()

                got = session.request("GET", "https://example.com/video.mp4", stream=True)

                self.assertIs(got, download)
                self.assertGreater(login_page.text_reads, 0)
                self.assertEqual(download.text_reads, 0)
                session.ensure_login.assert_called_once_with(
                    "user", "password", force=True, allow_qrcode_login=False,
                )
                self.assertEqual(session.backend.session.request.call_count, 2)
                self.assertTrue(session.backend.session.request.call_args.kwargs["stream"])

    def test_streamed_retry_still_rejects_login_page(self):
        response = _FakeDownloadResponse(
            {"Content-Type": "text/html"},
            '<form id="fm1"><input name="execution">统一身份认证</form>',
        )
        session = self._session_with(response)
        session._login_context = LoginContext("user", "password", None, False, {})
        session._ensure_login_context_matches_current_account = Mock()
        session.ensure_login = Mock()

        with self.assertRaises(ServerError):
            session.request("GET", "https://example.com/video.mp4", stream=True)

        self.assertEqual(session.backend.session.request.call_count, 2)

    def test_unstreamed_response_still_checks_for_a_login_page(self):
        response = _FakeDownloadResponse({}, "<html></html>")
        session = self._session_with(response)
        session.is_auth_failure_response = Mock(return_value=False)

        got = session.request("GET", "https://example.com/page")

        self.assertIs(got, response)
        session.is_auth_failure_response.assert_called_once_with(response)


if __name__ == '__main__':
    unittest.main()
