from __future__ import annotations

from auth.constant import LMS_LOGIN_URL
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class LMSSession(CommonLoginSession):
    """
    lms.xjtu.edu.cn 登录用的 Session
    """
    site_key = "lms"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_url = LMS_LOGIN_URL
        if not login_url.startswith(("http://", "https://")):
            login_url = f"https://{login_url}"

        login_util = NewLogin(login_url, session=self, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        self.reset_timeout()
        self.has_login = True

    _re_login = _login


# Backward compatibility for previous class name.
LMSLoginSession = LMSSession
