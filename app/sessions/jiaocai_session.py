from __future__ import annotations

from auth import ServerError
from auth.constant import JIAOCAI_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg


class JiaocaiSession(CommonLoginSession):
    """jiaocai.lib / jiaocai1.lib 共用会话。"""

    site_key = "jiaocai"
    site_name = "教材中心"
    supports_webvpn = True
    use_webvpn_when_off_campus = True

    USER_INFO_URL = "https://jiaocai.lib.xjtu.edu.cn/engine2/header/user-info"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enc = ""
        self.uid = ""

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.enc = ""
        self.uid = ""

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.enc = self.headers.get("X-Jiaocai-Enc", "")
        self.uid = self.headers.get("X-Jiaocai-Uid", "")

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = NewWebVPNLogin if self.access_mode == AccessMode.WEBVPN else NewLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(
                JIAOCAI_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        response = self.get(self.USER_INFO_URL, timeout=15, _skip_auth_check=True)
        try:
            data = (response.json() or {}).get("data") or {}
        except ValueError:
            data = {}
        self.uid = str(data.get("uid") or "")
        self.enc = str(data.get("enc") or "")
        if self.uid:
            self.headers["X-Jiaocai-Uid"] = self.uid
            self.headers["X-Jiaocai-Enc"] = self.enc
        elif "login.xjtu.edu.cn" in response.url:
            raise ServerError(102, "教材中心登录失败")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        response = self.get(self.USER_INFO_URL, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False
        try:
            data = (response.json() or {}).get("data") or {}
        except ValueError:
            return False
        return bool(data.get("uid"))
