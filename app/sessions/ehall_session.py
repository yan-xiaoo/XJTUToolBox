from auth import EHALL_LOGIN_URL
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class EhallSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    def _login(self, username, password, *args, **kwargs):
        login_util = NewLogin(EHALL_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        self.reset_timeout()
        self.has_login = True

    _re_login = _login
