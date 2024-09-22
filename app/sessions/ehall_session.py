from auth import EHALL_LOGIN_URL, Login
from .common_session import CommonLoginSession


class EhallSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    def login(self, username, password):
        login_util = Login(EHALL_LOGIN_URL, session=self)
        login_util.login(username, password)
        login_util.post_login()

        self.reset_timeout()
        self.has_login = True

    reLogin = login
