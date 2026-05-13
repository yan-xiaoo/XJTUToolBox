from __future__ import annotations

from auth import GMIS_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from auth.new_qrcode_login import NewQRCodeLogin, NewWebVPNQRCodeLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg


class GMISSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    site_key = "gmis"
    site_name = "研究生管理信息系统"
    supports_webvpn = True

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        qrcode_login_class = NewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else NewQRCodeLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(GMIS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: qrcode_login_class(GMIS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)),
            account_type=NewLogin.POSTGRADUATE,
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过研究生课表页面验证站点登录态。"""
        response = self.get(
            "https://gmis.xjtu.edu.cn/pyxx/pygl/xskbcx",
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False

        page = response.text
        return "drpxq" in page or "xskbcx" in page or "课表" in page
