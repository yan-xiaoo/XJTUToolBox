from __future__ import annotations

from auth import GMIS_LOGIN_URL
from auth.new_login import NewLogin
from app.utils.interactive_login import login_with_optional_mfa
from .common_session import CommonLoginSession
from ..utils import cfg


class GMISSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    site_key = "gmis"
    site_name = "研究生管理信息系统"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_util = NewLogin(GMIS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
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

        self.reset_timeout()
        self.has_login = True

    _re_login = _login
