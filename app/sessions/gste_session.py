from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from auth import GSTE_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin


class GSTESession(CommonLoginSession):
    """
    gste.xjtu.edu.cn 登录用的 Session
    此网站要求校园网内访问，因此校外必须采用 WebVPN 访问
    """
    site_key = "gste"
    site_name = "研究生评教系统"
    supports_webvpn = True

    class LoginMethod(enum.Enum):
        NORMAL = 0
        WEBVPN = 1

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        login_util = login_class(GSTE_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            account_type=NewLogin.POSTGRADUATE,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.login_method = self.LoginMethod.WEBVPN if self.access_mode == AccessMode.WEBVPN else self.LoginMethod.NORMAL

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
