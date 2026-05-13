from __future__ import annotations

from auth.constant import LMS_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from app.utils.interactive_login import login_with_optional_mfa
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
        login_util = login_class(login_url, session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            site_key=self.site_key,
            site_name=self.site_name,
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
