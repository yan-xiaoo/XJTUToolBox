from __future__ import annotations

from app.sessions.common_session import CommonLoginSession
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from auth.new_login import NewLogin
from jwapp.util import JwappNewLogin


class JwappSession(CommonLoginSession):
    """
    jwapp.xjtu.edu.cn 登录用的 Session
    """
    site_key = "jwapp"
    site_name = "移动教务系统"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_util = JwappNewLogin(session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            account_type=NewLogin.UNDERGRADUATE,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login
