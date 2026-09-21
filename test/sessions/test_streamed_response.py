import unittest
from unittest.mock import Mock

from app.sessions.lms_session import LMSSession

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
        self.addCleanup(lambda: setattr(session.backend.session, "request", Mock()))
        return session

    def test_streamed_response_skips_the_login_page_check_entirely(self):
        response = _FakeDownloadResponse({"Content-Length": str(954 * 1024 * 1024)})
        session = self._session_with(response)
        session.is_auth_failure_response = Mock(return_value=False)

        got = session.request("GET", "https://example.com/video.mp4", stream=True)

        self.assertIs(got, response)
        self.assertEqual(response.text_reads, 0)
        session.is_auth_failure_response.assert_not_called()

    def test_unstreamed_response_still_checks_for_a_login_page(self):
        response = _FakeDownloadResponse({}, "<html></html>")
        session = self._session_with(response)
        session.is_auth_failure_response = Mock(return_value=False)

        got = session.request("GET", "https://example.com/page")

        self.assertIs(got, response)
        session.is_auth_failure_response.assert_called_once_with(response)


if __name__ == '__main__':
    unittest.main()
