import enum

from app.sessions.common_session import CommonLoginSession
from app.utils import cfg
from attendance.attendance import AttendanceNewLogin, AttendanceNewWebVPNLogin
from auth import WEBVPN_LOGIN_URL, GSTE_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin


class GSTESession(CommonLoginSession):
    """
    gste.xjtu.edu.cn 登录用的 Session
    此网站要求校园网内访问，因此校外必须采用 WebVPN 访问
    """
    class LoginMethod(enum.Enum):
        NORMAL = 0
        WEBVPN = 1

    def __init__(self, time=15*60):
        super().__init__(time)
        self.login_method = None

    def login(self, username, password):
        self.cookies.clear()
        login_util = NewLogin(GSTE_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        self.login_method = self.LoginMethod.NORMAL

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username, password):
        # 目前 WebVPN 访问分为两个步骤
        # 1. 登录 WebVPN 自身，此时采用不经过 WebVPN 中介的接口
        # 2. 登录 WebVPN 之后，再登录一次目标网站。此时采用经过 WebVPN 中介的接口
        self.cookies.clear()
        login_util = NewLogin(WEBVPN_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        gste_login_util = NewWebVPNLogin(GSTE_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
        gste_login_util.login_or_raise(username, password)

        self.login_method = self.LoginMethod.WEBVPN

        self.reset_timeout()
        self.has_login = True

    reLogin = login