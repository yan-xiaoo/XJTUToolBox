from __future__ import annotations

import time

from auth import ServerError
from auth.constant import DZPZ_LOGIN_URL
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class DzpzSession(CommonLoginSession):
    """dzpz.xjtu.edu.cn 电子成绩单，必须从 Login.jsp 进入。"""

    site_key = "dzpz"
    site_name = "电子成绩单"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    OS_INFO_URL = "https://dzpz.xjtu.edu.cn/api/system/info/getOSinfo"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user_id = ""

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.user_id = ""

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.user_id = self.headers.get("X-DZPZ-User-Id", "")

    def _store_user_id(self, user_id: str) -> None:
        self.user_id = user_id
        self.headers["X-DZPZ-User-Id"] = user_id

    def _find_loginidweaver(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "loginidweaver" and cookie.value:
                return cookie.value
        return ""

    def _fetch_user_id_from_api(self) -> str:
        response = self.get(
            f"{self.OS_INFO_URL}?__random__={int(time.time() * 1000)}",
            headers={"Referer": "https://dzpz.xjtu.edu.cn/wui/index.html"},
            timeout=15,
            _skip_auth_check=True,
        )
        try:
            resource_id = str((response.json() or {}).get("resourceid") or "")
        except ValueError:
            return ""
        if resource_id and resource_id != "0":
            return resource_id
        return ""

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(
                DZPZ_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        user_id = self._find_loginidweaver() or self._fetch_user_id_from_api()
        if not user_id:
            self.get(DZPZ_LOGIN_URL, allow_redirects=True, timeout=20, _skip_auth_check=True)
            user_id = self._find_loginidweaver() or self._fetch_user_id_from_api()
        if not user_id:
            raise ServerError(102, "登录失败：无法获取电子凭证用户 ID")
        self._store_user_id(user_id)
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        user_id = self._fetch_user_id_from_api()
        if not user_id:
            return False
        self._store_user_id(user_id)
        return True
