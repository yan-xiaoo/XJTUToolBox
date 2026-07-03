from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from auth import NewLogin
from app.sessions.common_session import CommonLoginSession


class VenueSession(CommonLoginSession):
    """体育场馆预约系统的登录 Session。

    认证流程：
    1. perform_cas_login → CAS OAuth2.0 登录，获取 TGC cookie
    2. 用 TGC 请求 OAuth authorize URL → 自动跳转到 202.117.17.144
    3. 202.117.17.144 设置 JSESSIONID cookie
    """

    site_key = "venue"
    site_name = "体育场馆"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    OAUTH_URL = (
        "https://login.xjtu.edu.cn/cas/oauth2.0/authorize?"
        "response_type=code&client_id=1439&"
        "redirect_uri=https://org.xjtu.edu.cn/openplatform/oauth/authorizesw?"
        "redirect_uri=http://202.117.17.144/xjtu/cas/oauth2url.html&state=1"
    )
    BASE_URL = "http://202.117.17.144:8071"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        # Step 1: CAS OAuth2.0 登录
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(
                self.OAUTH_URL, session=self,
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )

        # Step 2: 跟随 OAuth 跳转链，获取 JSESSIONID
        r = self.get(self.OAUTH_URL, allow_redirects=True, _skip_auth_check=True)
        if "CAS" in r.url.upper() or "login" in r.url:
            raise ValueError(f"场馆 OAuth 跳转失败，仍在 CAS 页面: {r.url}")

        # Step 3: 验证最终是否到了体育馆页面
        if "202.117.17.144" not in r.url:
            raise ValueError(f"场馆登录失败，最终 URL: {r.url}")

        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """请求场馆列表页面验证登录态。"""
        try:
            r = self.get(
                f"{self.BASE_URL}/product/index.html",
                headers={"Referer": f"{self.BASE_URL}/"},
                timeout=15,
                _skip_auth_check=True,
            )
            if r.status_code != 200:
                return False
            # 页面包含这些特征表示登录有效
            return "product" in r.text.lower() and "serviceid" not in r.text.lower()
        except Exception:
            return False

    def refresh_login(self) -> bool:
        """刷新场馆登录态。"""
        try:
            self._re_login(
                self._last_context.username,
                self._last_context.password,
                **self._last_context.kwargs,
            )
            return True
        except Exception:
            return False

    def keep_alive(self) -> None:
        """无操作 —— 场馆无专门心跳 API。"""
        pass
