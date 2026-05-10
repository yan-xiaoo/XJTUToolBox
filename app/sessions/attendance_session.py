from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode, SessionBackend
from app.utils import cfg
from attendance.attendance import AttendanceNewLogin, AttendanceNewWebVPNLogin
from auth import WEBVPN_LOGIN_URL
from auth.new_login import NewLogin


class AttendanceSession(CommonLoginSession):
    """
    bkkq.xjtu.edu.cn 登录用的 Session
    """
    site_key = "attendance"
    supports_webvpn = True

    class LoginMethod(enum.Enum):
        NORMAL = 0
        WEBVPN = 1

    def __init__(self, backend: SessionBackend | None = None, webvpn_backend: SessionBackend | None = None,
                 timeout: int = 15 * 60) -> None:
        super().__init__(backend=backend, timeout=timeout)
        self.normal_backend = self.backend
        self.webvpn_backend = webvpn_backend or SessionBackend(AccessMode.WEBVPN, timeout=timeout)

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.set_backend(self.normal_backend)
        is_postgraduate = kwargs.get("is_postgraduate") is True
        login_util = AttendanceNewLogin(self, is_postgraduate=is_postgraduate, visitor_id=str(cfg.loginId.value))
        login_util.login_or_raise(username, password)

        self.login_method = self.LoginMethod.NORMAL

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username: str, password: str, is_postgraduate: bool = False) -> None:
        """通过 WebVPN 登录考勤系统。"""
        # 目前 WebVPN 访问分为两个步骤
        # 1. 登录 WebVPN 自身，此时采用不经过 WebVPN 中介的接口
        # 2. 登录 WebVPN 之后，再登录一次目标网站。此时采用经过 WebVPN 中介的接口
        with self.login_lock:
            self.clear_site_state()
            self.set_backend(self.webvpn_backend)

            with self.webvpn_backend.login_lock:
                if not self.webvpn_backend.has_login:
                    login_util = NewLogin(WEBVPN_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
                    login_util.login_or_raise(username, password)
                    self.webvpn_backend.has_login = True

            attendance_login_util = AttendanceNewWebVPNLogin(self, is_postgraduate=is_postgraduate,
                                                             visitor_id=str(cfg.loginId.value))
            attendance_login_util.login_or_raise(username, password)

            self.login_method = self.LoginMethod.WEBVPN

            self.reset_timeout()
            self.has_login = True

    _re_login = _login
