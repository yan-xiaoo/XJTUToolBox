from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from auth import ServerError
from auth.constant import CAMPUS_CARD_LOGIN_URL, MOBILE_BROWSER_UA
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class CampusCardSession(CommonLoginSession):
    """ncard.xjtu.edu.cn：CAS ticket 兑换 JWT。"""

    site_key = "campus_card"
    site_name = "校园卡"
    supports_webvpn = False
    use_webvpn_when_off_campus = False
    user_agent = MOBILE_BROWSER_UA

    TOKEN_URL = "https://ncard.xjtu.edu.cn/berserker-auth/oauth/token"
    USER_URL = "https://ncard.xjtu.edu.cn/berserker-base/user?synAccessSource=h5"
    TOKEN_BASIC_AUTH = "Basic bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm06bW9iaWxlX3NlcnZpY2VfcGxhdGZvcm1fc2VjcmV0"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.access_token = ""
        self.card_account = ""
        self.user_name = ""
        self.student_no = ""
        self.headers["synAccessSource"] = "h5"

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.access_token = ""
        self.card_account = ""
        self.user_name = ""
        self.student_no = ""
        self.headers["synAccessSource"] = "h5"

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.access_token = self.headers.get("X-Card-Access-Token", "")
        self.card_account = self.headers.get("X-Card-Account", "")
        self.user_name = self.headers.get("X-Card-Name", "")
        self.student_no = self.headers.get("X-Card-Sno", "")
        if self.access_token:
            self.headers["Synjones-Auth"] = f"bearer {self.access_token}"
        self.headers.setdefault("synAccessSource", "h5")

    def _store_tokens(self) -> None:
        self.headers["Synjones-Auth"] = f"bearer {self.access_token}"
        self.headers["synAccessSource"] = "h5"
        self.headers["X-Card-Access-Token"] = self.access_token
        self.headers["X-Card-Account"] = self.card_account
        self.headers["X-Card-Name"] = self.user_name
        self.headers["X-Card-Sno"] = self.student_no

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(
                CAMPUS_CARD_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        if not self._complete_login():
            raise ServerError(102, "校园卡 SSO 未拿到 ticket，需要重新登录")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def _complete_login(self) -> bool:
        response = self.get(CAMPUS_CARD_LOGIN_URL, allow_redirects=True, timeout=20, _skip_auth_check=True)
        if self._try_ticket(response.url):
            return True
        response = self.get(CAMPUS_CARD_LOGIN_URL, allow_redirects=True, timeout=20, _skip_auth_check=True)
        return self._try_ticket(response.url)

    def _try_ticket(self, url: str) -> bool:
        if "ticket=" not in url or "ncard.xjtu.edu.cn" not in url:
            return False
        ticket = unquote(parse_qs(urlparse(url).query).get("ticket", [""])[0])
        if not ticket:
            return False
        token_response = self.post(
            self.TOKEN_URL,
            headers={"Authorization": self.TOKEN_BASIC_AUTH},
            data={
                "username": ticket,
                "password": ticket,
                "grant_type": "password",
                "scope": "all",
                "loginFrom": "h5",
                "logintype": "sso",
                "device_token": "h5",
                "synAccessSource": "h5",
            },
            timeout=20,
            _skip_auth_check=True,
        )
        try:
            token = token_response.json().get("access_token")
        except ValueError:
            return False
        if not token:
            return False
        self.access_token = token
        self.headers["Synjones-Auth"] = f"bearer {token}"
        user_response = self.get(
            self.USER_URL,
            headers={"synjones-auth": f"bearer {token}", "synAccessSource": "h5"},
            timeout=15,
            _skip_auth_check=True,
        )
        try:
            data = user_response.json().get("data") or {}
        except ValueError:
            data = {}
        self.card_account = str(data.get("cardAccount") or "")
        self.user_name = str(data.get("name") or "").strip()
        self.student_no = str(data.get("sno") or "")
        self._store_tokens()
        return True

    def validate_login(self) -> bool:
        if not self.access_token:
            return False
        response = self.get(
            "https://ncard.xjtu.edu.cn/berserker-app/ykt/tsm/queryCard?synAccessSource=h5",
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False
        try:
            return response.json().get("code") == 200
        except ValueError:
            return False
