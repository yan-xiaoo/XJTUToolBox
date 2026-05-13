from __future__ import annotations

from auth.constant import LMS_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from auth.new_qrcode_login import NewQRCodeLogin, NewWebVPNQRCodeLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg


class LMSSession(CommonLoginSession):
    """
    lms.xjtu.edu.cn 登录用的 Session
    """
    site_key = "lms"
    site_name = "思源学堂"
    supports_webvpn = True

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_url = LMS_LOGIN_URL
        if not login_url.startswith(("http://", "https://")):
            login_url = f"https://{login_url}"

        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        qrcode_login_class = NewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else NewQRCodeLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(login_url, session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: qrcode_login_class(login_url, session=self, visitor_id=str(cfg.loginId.value)),
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过思源学堂用户主页验证站点登录态。"""
        response = self.get(
            "https://lms.xjtu.edu.cn/user/index",
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False

        page = response.text
        return "globalData" in page and "user" in page


# Backward compatibility for previous class name.
LMSLoginSession = LMSSession
