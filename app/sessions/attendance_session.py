from app.sessions.common_session import CommonLoginSession
from attendance import AttendanceLogin, AttendanceWebVPNLogin


class AttendanceSession(CommonLoginSession):
    """
    bkkq.xjtu.edu.cn 登录用的 Session
    """
    def login(self, username, password):
        login_util = AttendanceLogin(self)
        login_util.login(username, password)
        login_util.post_login()

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username, password):
        login_util = AttendanceWebVPNLogin(self)
        login_util.login(username, password)
        login_util.post_login()

        self.reset_timeout()
        self.has_login = True

    reLogin = login