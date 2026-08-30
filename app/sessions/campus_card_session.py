from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

from auth import ServerError
from auth.constant import CAMPUS_CARD_LOGIN_URL, MOBILE_BROWSER_UA
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg

if TYPE_CHECKING:
    from ..utils.session_persistence import SiteSnapshot


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

    def restore_site_snapshot(self, snapshot: SiteSnapshot) -> None:
        super().restore_site_snapshot(snapshot)
        auth_header = str(self.headers.get("Synjones-Auth", ""))
        scheme, separator, token = auth_header.partition(" ")
        self.access_token = token.strip() if separator and scheme.lower() == "bearer" else ""
        self.card_account = ""
        self.user_name = ""
        self.student_no = ""
        self.headers["synAccessSource"] = "h5"

    def _store_token(self) -> None:
        self.headers["Synjones-Auth"] = f"bearer {self.access_token}"
        self.headers["synAccessSource"] = "h5"

    def _load_user_profile(self) -> None:
        response = self.get(
            self.USER_URL,
            timeout=15,
            _skip_auth_check=True,
        )
        if not response.ok:
            raise ServerError(1, "校园卡用户资料请求失败")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServerError(1, "校园卡用户资料返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise ServerError(1, "校园卡用户资料返回的数据格式错误")
        if "code" in payload and str(payload["code"]) != "200":
            raise ServerError(1, "校园卡用户资料查询失败")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ServerError(1, "校园卡用户资料返回的数据格式错误")

        values: dict[str, str] = {}
        for field in ("name", "sno", "cardAccount"):
            value = data.get(field)
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise ServerError(1, "校园卡用户资料缺少必要字段")
            text = str(value).strip()
            if not text:
                raise ServerError(1, "校园卡用户资料缺少必要字段")
            values[field] = text

        self.user_name = values["name"]
        self.student_no = values["sno"]
        self.card_account = values["cardAccount"]

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
        self._store_token()
        self._load_user_profile()
        return True

    def is_auth_failure_response(self, response) -> bool:
        if super().is_auth_failure_response(response):
            return True
        try:
            payload = response.json()
        except ValueError:
            return False
        if not isinstance(payload, dict):
            return False
        message = str(payload.get("message") or "")
        return str(payload.get("code")) == "401" or "其他设备" in message or "未登录" in message

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
            payload = response.json()
        except ValueError:
            return False
        if not isinstance(payload, dict) or str(payload.get("code")) != "200":
            return False
        if not all((self.user_name, self.student_no, self.card_account)):
            try:
                self._load_user_profile()
            except ServerError:
                return False
        return True
