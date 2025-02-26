from app.sessions.common_session import CommonLoginSession
from jwapp import JwappLogin


class JwappSession(CommonLoginSession):
    """
    jwapp.xjtu.edu.cn 登录用的 Session
    """
    def login(self, username, password):
        login_util = JwappLogin(session=self)
        login_util.login(username, password)
        login_util.post_login()

        self.reset_timeout()
        self.has_login = True

    reLogin = login
