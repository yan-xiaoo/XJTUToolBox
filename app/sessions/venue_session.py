"""体育场馆会话（CAS OAuth2.0 → SESSION cookie on port 8080）。"""

from __future__ import annotations

import logging

import requests

from auth import NewLogin
from app.sessions.common_session import CommonLoginSession

_log = logging.getLogger("default")


class VenueSession(CommonLoginSession):
    """体育场馆预订系统登录会话。

    登录流程（通过移动交大 superapp 进入）：
    1. CAS OAuth2.0 登录（appId=1659）
    2. org.xjtu.edu.cn → CAS → 202.117.17.144:8080/web/cas/oauth2url.html
    3. 202.117.17.144:8080 设置 SESSION cookie → 302 → /web/index.html
    """

    site_key = "venue"
    site_name = "体育场馆"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    OAUTH_URL = (
        "https://org.xjtu.edu.cn/openplatform/oauth/authorize?"
        "responseType=code&scope=user_info&appId=1659&state=1&"
        "redirectUri=http://202.117.17.144:8080/web/cas/oauth2url.html"
    )
    BASE_URL = "http://202.117.17.144:8080"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        # CAS OAuth2.0 登录 → 自动跟随跳转链到 8080
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

        # 访问首页确认登录状态
        r = self.get(
            f"{self.BASE_URL}/web/index.html",
            allow_redirects=True,
            timeout=15,
            _skip_auth_check=True,
        )
        r.raise_for_status()

        if "userno" not in r.text or 'value=""' in r.text.split('userno')[1][:50]:
            raise ValueError("场馆登录失败：userno 未获取")

        _log.info("Venue login OK, cookies: %s",
                  requests.utils.dict_from_cookiejar(self.cookies))

    _re_login = _login

    def validate_login(self) -> bool:
        """通过 API 请求验证登录状态。"""
        try:
            r = self.get(
                f"{self.BASE_URL}/web/product/productData.html",
                params={"page": "1", "rows": "8",
                        "merccode": "100001", "remark": "defaultProList"},
                headers={"Referer": f"{self.BASE_URL}/web/index.html"},
                timeout=15,
                _skip_auth_check=True,
            )
            if r.status_code != 200:
                return False
            data = r.json()
            return isinstance(data, list) and len(data) > 0
        except Exception:
            return False

    def keep_alive(self, **kwargs) -> dict:
        return {"valid": self.validate_login()}
