from __future__ import annotations

from auth import ServerError
from auth.constant import LIBRARY_LOGIN_URL, MOBILE_BROWSER_UA
from auth.new_login import NewLogin, NewWebVPNLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg


def looks_like_seat_page(body: str) -> bool:
    if "移动端模式" in body:
        return False
    return any(marker in body for marker in ("btn-group", "tab-select", "qseat", "座位", "scount"))


class LibrarySession(CommonLoginSession):
    """rg.lib.xjtu.edu.cn:8086 座位系统，CAS cookie 会话。"""

    site_key = "library"
    site_name = "图书馆"
    supports_webvpn = True
    use_webvpn_when_off_campus = True
    user_agent = MOBILE_BROWSER_UA

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(
                LIBRARY_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        response = self.get(LIBRARY_LOGIN_URL, allow_redirects=True, timeout=20, _skip_auth_check=True)
        if "移动端模式" in response.text:
            raise ServerError(1, "请浏览器调成移动端模式访问！")
        if not looks_like_seat_page(response.text):
            raise ServerError(1, "图书馆座位系统登录失败，请确认已连接校园网或 WebVPN")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        response = self.get(LIBRARY_LOGIN_URL, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False
        return looks_like_seat_page(response.text)
