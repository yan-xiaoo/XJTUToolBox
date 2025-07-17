import enum

from app.sessions.common_session import CommonLoginSession
from attendance.attendance import AttendanceNewLogin, AttendanceNewWebVPNLogin


class AttendanceSession(CommonLoginSession):
    """
    bkkq.xjtu.edu.cn 登录用的 Session
    """
    class LoginMethod(enum.Enum):
        NORMAL = 0
        WEBVPN = 1

    def __init__(self, time=15*60):
        super().__init__(time)
        self.login_method = None

    def login(self, username, password):
        login_util = AttendanceNewLogin(self)
        login_util.login(username, password)

        self.login_method = self.LoginMethod.NORMAL

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username, password):
        login_util = AttendanceNewWebVPNLogin(self)
        login_util.login(username, password)

        self.login_method = self.LoginMethod.WEBVPN

        self.reset_timeout()
        self.has_login = True

    reLogin = login