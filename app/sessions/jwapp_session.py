from app.sessions.common_session import CommonLoginSession
from app.utils import cfg
from jwapp.util import JwappNewLogin


class JwappSession(CommonLoginSession):
    """
    jwapp.xjtu.edu.cn 登录用的 Session
    """
    def _login(self, username, password, *args, **kwargs):
        login_util = JwappNewLogin(session=self, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        self.reset_timeout()
        self.has_login = True

    _re_login = _login
