from __future__ import annotations

from auth.new_login import NewLogin, NewWebVPNLogin
from auth.new_qrcode_login import NewQRCodeLogin, NewWebVPNQRCodeLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg

QMS_LOGIN_URL = "https://qms.xjtu.edu.cn/quality-client/my/tasks"
QMS_TASKS_API = "https://qms.xjtu.edu.cn/api/quality/my/tasks"


class QMSSession(CommonLoginSession):
    """西安交通大学 QMS（畅评 TronGauge）评教系统 Session。"""

    site_key = "qms"
    site_name = "学生评教"
    supports_webvpn = True
    use_webvpn_when_off_campus = False

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        qrcode_login_class = NewWebVPNQRCodeLogin if self.access_mode == AccessMode.WEBVPN else NewQRCodeLogin
        account = kwargs.get("account")
        account_type = NewLogin.UNDERGRADUATE
        if account is not None and getattr(account, "type", None) == getattr(account, "POSTGRADUATE", None):
            account_type = NewLogin.POSTGRADUATE
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(
                QMS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=lambda: qrcode_login_class(
                QMS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            account_type=account_type,
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """用 QMS 任务接口验证登录态。"""
        response = self.get(
            QMS_TASKS_API,
            params={"planStatus": "IN_PROGRESS"},
            headers={"Accept": "application/json, text/plain, */*"},
            timeout=15,
            allow_redirects=False,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False
        try:
            result = response.json()
        except ValueError:
            return False
        return isinstance(result, dict) and isinstance(result.get("data"), list)
