from __future__ import annotations

import unittest

from requests.cookies import create_cookie

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode
from auth import ATTENDANCE_WEBVPN_URL
from app.utils.session_manager import SessionManager
import app.utils.session_manager as session_manager_module
from app.utils.session_persistence import SiteSnapshot


class NormalTestSession(CommonLoginSession):
    """用于验证普通访问模式创建逻辑的测试 Session。"""

    site_key = "normal_test"
    default_access_mode = AccessMode.NORMAL

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        """模拟登录流程。"""

    def _re_login(self, username: str, password: str, **kwargs: object) -> None:
        """模拟重新登录流程。"""


class WebVPNTestSession(CommonLoginSession):
    """用于验证 WebVPN 访问模式创建逻辑的测试 Session。"""

    site_key = "webvpn_test"
    default_access_mode = AccessMode.WEBVPN
    supports_webvpn = True

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        """模拟登录流程。"""

    def _re_login(self, username: str, password: str, **kwargs: object) -> None:
        """模拟重新登录流程。"""


class ProbeResponse:
    """用于模拟校园网探测请求响应。"""

    def __init__(self, status_code: int) -> None:
        """保存响应状态码。"""
        self.status_code = status_code
        self.closed = False

    def close(self) -> None:
        """记录响应已关闭。"""
        self.closed = True


class SessionManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 清除类变量里累计注册的 session
        SessionManager.sessions.clear()
        self.s1 = SessionManager()
        self.s2 = SessionManager()

    def test_add(self) -> None:
        self.s1.register(NormalTestSession, "normal")
        self.s1.register(WebVPNTestSession, "webvpn")
        normal_session = self.s1.get_session("normal")
        webvpn_session = self.s1.get_session("webvpn")

        self.assertIsInstance(normal_session, NormalTestSession)
        self.assertIsInstance(webvpn_session, WebVPNTestSession)
        self.assertIs(normal_session.backend, self.s1.get_backend(AccessMode.NORMAL))
        self.assertIs(webvpn_session.backend, self.s1.get_backend(AccessMode.WEBVPN))
        self.assertIs(normal_session.session_manager, self.s1)
        self.assertIs(webvpn_session.session_manager, self.s1)
        self.assertRaises(ValueError, self.s2.get_session, "webvpn")
        self.assertRaises(ValueError, self.s2.get_session, "normal")

    def test_global_add(self) -> None:
        self.s1.global_register(NormalTestSession, "normal")
        self.s1.global_register(WebVPNTestSession, "webvpn")

        self.assertIsInstance(self.s1.get_session("normal"), NormalTestSession)
        self.assertIsInstance(self.s1.get_session("webvpn"), WebVPNTestSession)
        self.assertIsInstance(self.s2.get_session("normal"), NormalTestSession)
        self.assertIsInstance(self.s2.get_session("webvpn"), WebVPNTestSession)

    def test_exist(self) -> None:
        self.s1.register(NormalTestSession, "normal")
        self.assertTrue(self.s1.exists("normal"))
        self.assertFalse(self.s1.exists("webvpn"))
        self.assertFalse(self.s2.exists("normal"))
        self.assertFalse(self.s2.exists("webvpn"))

    def test_stable(self) -> None:
        self.s1.register(NormalTestSession, "normal")
        s1 = self.s1.get_session("normal")
        s2 = self.s1.get_session("normal")
        self.assertIs(s1, s2)

    def test_rename(self) -> None:
        self.s1.register(NormalTestSession, "normal")
        self.s1.rename("normal", "renamed_normal")
        self.assertTrue(self.s1.exists("renamed_normal"))
        self.assertFalse(self.s1.exists("normal"))

        self.s1.global_register(WebVPNTestSession, "webvpn")
        self.assertRaises(ValueError, self.s1.rename, "webvpn", "renamed_webvpn")
        self.assertRaises(ValueError, self.s2.rename, "webvpn", "renamed_webvpn")

    def test_access_policy_change_clears_restored_site_state(self) -> None:
        """访问策略切换应清理恢复出的站点候选态并要求 WebVPN 后端重新验证。"""
        self.s1.register(WebVPNTestSession, "webvpn")
        webvpn_backend = self.s1.get_backend(AccessMode.WEBVPN)
        webvpn_backend.session.cookies.set_cookie(create_cookie(name="webvpn", value="cookie"))
        self.s1._pending_site_snapshots["webvpn"] = SiteSnapshot(
            site_key="webvpn_test",
            access_mode=AccessMode.WEBVPN.value,
            headers={"Authorization": "Bearer restored"},
            saved_at=1.0,
        )
        self.s1._pending_site_snapshots["later"] = SiteSnapshot(
            site_key="later",
            access_mode=AccessMode.WEBVPN.value,
            headers={"Authorization": "Bearer pending"},
            saved_at=1.0,
        )
        session = self.s1.get_session("webvpn")

        self.assertEqual(session.access_mode, AccessMode.WEBVPN)
        self.assertTrue(session.has_login)
        self.assertEqual(session.headers["Authorization"], "Bearer restored")

        self.s1.handle_access_policy_changed(preferred=AccessMode.NORMAL)

        self.assertEqual(session.access_mode, AccessMode.NORMAL)
        self.assertFalse(session.has_login)
        self.assertNotIn("Authorization", session.headers)
        self.assertEqual(self.s1._pending_site_snapshots, {})
        self.assertTrue(webvpn_backend.has_login)
        self.assertFalse(webvpn_backend.webvpn_has_login)
        self.assertTrue(webvpn_backend.restored_auth_candidate)

    def test_campus_probe_uses_attendance_target(self) -> None:
        """自动访问方式探测应使用考勤系统目标域。"""
        calls: list[tuple[str, object, object]] = []
        response = ProbeResponse(302)
        original_get = session_manager_module.requests.get

        def fake_get(url: str, **kwargs: object) -> ProbeResponse:
            """记录探测请求并返回可达响应。"""
            calls.append((url, kwargs.get("allow_redirects"), kwargs.get("timeout")))
            return response

        session_manager_module.requests.get = fake_get
        try:
            result = self.s1.can_reach_campus_network(timeout=3.0)
        finally:
            session_manager_module.requests.get = original_get

        self.assertTrue(result)
        self.assertEqual(calls, [(ATTENDANCE_WEBVPN_URL, False, 3.0)])
        self.assertTrue(response.closed)

    def test_campus_probe_rejects_bad_gateway(self) -> None:
        """校外访问 bkkq 返回 5xx 时不应被当作可直连校园网。"""
        response = ProbeResponse(502)
        original_get = session_manager_module.requests.get

        def fake_get(url: str, **kwargs: object) -> ProbeResponse:
            """返回校外不可达时常见的 502 响应。"""
            return response

        session_manager_module.requests.get = fake_get
        try:
            result = self.s1.can_reach_campus_network(timeout=3.0)
        finally:
            session_manager_module.requests.get = original_get

        self.assertFalse(result)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
