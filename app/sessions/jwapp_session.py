from __future__ import annotations

from app.sessions.common_session import CommonLoginSession
from app.utils import cfg
from auth.new_login import NewLogin
from jwapp.util import JwappNewLogin, JwappNewQRCodeLogin, JwappNewWebVPNLogin, JwappNewWebVPNQRCodeLogin
from .session_backend import AccessMode


class JwappSession(CommonLoginSession):
    """
    jwapp.xjtu.edu.cn 登录用的 Session
    """
    site_key = "jwapp"
    site_name = "移动教务系统"
    supports_webvpn = True

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = JwappNewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else JwappNewLogin
        qrcode_login_class = JwappNewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else JwappNewQRCodeLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: qrcode_login_class(session=self, visitor_id=str(cfg.loginId.value)),
            account_type=NewLogin.UNDERGRADUATE,
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过移动教务的通用接口验证站点登录态。"""
        if "Authorization" not in self.headers:
            return False

        response = self.get(
            "https://jwapp.xjtu.edu.cn/api/biz/v410/common/school/time",
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False

        try:
            result = response.json()
        except ValueError:
            return False

        return result.get("code") == 200
