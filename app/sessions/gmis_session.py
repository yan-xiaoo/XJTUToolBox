from auth import GMIS_LOGIN_URL
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class GMISSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    def login(self, username, password):
        login_util = NewLogin(GMIS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        login_util.login(username, password, account_type=NewLogin.POSTGRADUATE)

        self.reset_timeout()
        self.has_login = True

    reLogin = login
