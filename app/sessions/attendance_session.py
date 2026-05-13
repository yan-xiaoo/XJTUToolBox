from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from attendance.attendance import AttendanceNewLogin, AttendanceNewWebVPNLogin
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

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        is_postgraduate = kwargs.get("is_postgraduate") is True
        login_class = AttendanceNewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else AttendanceNewLogin
        login_util = login_class(self, is_postgraduate=is_postgraduate, visitor_id=str(cfg.loginId.value))
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

        self.login_method = self.LoginMethod.WEBVPN if self.access_mode == AccessMode.WEBVPN else self.LoginMethod.NORMAL

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

        response = self.post(url, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False

        try:
            result = response.json()
        except ValueError:
            return False

        return result.get("success") is True
