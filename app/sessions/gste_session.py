from __future__ import annotations

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode
from app.utils import cfg
from auth import GSTE_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from auth.new_qrcode_login import NewQRCodeLogin, NewWebVPNQRCodeLogin


class GSTESession(CommonLoginSession):
    """
    gste.xjtu.edu.cn 登录用的 Session
    此网站要求校园网内访问，因此校外必须采用 WebVPN 访问
    """
    site_key = "gste"
    site_name = "研究生评教系统"
    supports_webvpn = True

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        qrcode_login_class = NewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else NewQRCodeLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(GSTE_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: qrcode_login_class(GSTE_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)),
            account_type=NewLogin.POSTGRADUATE,
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过研究生评教问卷列表页验证站点登录态。"""
        url = "http://gste.xjtu.edu.cn/app/sshd4Stu/list.do"

        response = self.get(url, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False

        page = response.text
        return "sshd4Stu" in page or "questionnaire" in page or "评教" in page or response.url.startswith(url)
