from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode, SessionBackend
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from attendance.attendance import AttendanceNewLogin, AttendanceNewWebVPNLogin
from auth import WEBVPN_LOGIN_URL, getVPNUrl
from auth.new_login import NewLogin


class AttendanceSession(CommonLoginSession):
    """
    bkkq.xjtu.edu.cn 登录用的 Session
    """
    site_key = "attendance"
    site_name = "考勤系统"
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
        account, mfa_provider = self.get_login_context(kwargs)
        account_type = NewLogin.POSTGRADUATE if is_postgraduate else NewLogin.UNDERGRADUATE
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            account_type=account_type,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.login_method = self.LoginMethod.NORMAL

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username: str, password: str, is_postgraduate: bool = False, **kwargs: object) -> None:
        """通过 WebVPN 登录考勤系统。"""
        # 目前 WebVPN 访问分为两个步骤
        # 1. 登录 WebVPN 自身，此时采用不经过 WebVPN 中介的接口
        # 2. 登录 WebVPN 之后，再登录一次目标网站。此时采用经过 WebVPN 中介的接口
        with self.login_lock:
            self.clear_site_state()
            self.set_backend(self.webvpn_backend)
            account, mfa_provider = self.get_login_context(kwargs)
            account_type = NewLogin.POSTGRADUATE if is_postgraduate else NewLogin.UNDERGRADUATE

            with self.webvpn_backend.login_lock:
                if self.webvpn_backend.has_timeout():
                    self.webvpn_backend.has_login = False
                if not self.webvpn_backend.has_login:
                    login_util = NewLogin(WEBVPN_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
                    login_with_optional_mfa(
                        login_util,
                        username,
                        password,
                        account,
                        mfa_provider,
                        account_type=account_type,
                        site_key="webvpn",
                        site_name="WebVPN",
                    )
                    self.webvpn_backend.has_login = True

            attendance_login_util = AttendanceNewWebVPNLogin(self, is_postgraduate=is_postgraduate,
                                                             visitor_id=str(cfg.loginId.value))
            login_with_optional_mfa(
                attendance_login_util,
                username,
                password,
                account,
                mfa_provider,
                account_type=account_type,
                site_key=self.site_key,
                site_name=self.site_name,
            )

            self.login_method = self.LoginMethod.WEBVPN

            self.reset_timeout()
            self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过考勤系统学生信息接口验证站点登录态。"""
        if "Synjones-Auth" not in self.headers:
            return False

        is_postgraduate = False
        if self._login_context is not None:
            is_postgraduate = self._login_context.kwargs.get("is_postgraduate") is True

        domain = "yjskq.xjtu.edu.cn" if is_postgraduate else "bkkq.xjtu.edu.cn"
        url = f"https://{domain}/attendance-student/global/getStuInfo"
        if self.login_method == self.LoginMethod.WEBVPN:
            url = getVPNUrl(url)

        response = self.post(url, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False

        try:
            result = response.json()
        except ValueError:
            return False

        return result.get("success") is True
