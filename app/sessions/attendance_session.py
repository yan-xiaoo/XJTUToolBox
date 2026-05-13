from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode
from app.utils import cfg
from attendance.attendance import (
    AttendanceNewLogin,
    AttendanceNewQRCodeLogin,
    AttendanceNewWebVPNLogin,
    AttendanceNewWebVPNQRCodeLogin,
)
from auth.new_login import NewLogin


class AttendanceSession(CommonLoginSession):
    """
    bkkq.xjtu.edu.cn 登录用的 Session
    """
    site_key = "attendance"
    site_name = "考勤系统"
    supports_webvpn = True

    class LoginMethod(enum.Enum):
        """
        考勤系统登录方式。
        """
        NORMAL = 0
        WEBVPN = 1

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        is_postgraduate = kwargs.get("is_postgraduate") is True
        login_class = AttendanceNewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else AttendanceNewLogin
        qrcode_login_class = AttendanceNewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else AttendanceNewQRCodeLogin
        account_type = NewLogin.POSTGRADUATE if is_postgraduate else NewLogin.UNDERGRADUATE
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(self, is_postgraduate=is_postgraduate, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: qrcode_login_class(self, is_postgraduate=is_postgraduate, visitor_id=str(cfg.loginId.value)),
            account_type=account_type,
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
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
