from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

from auth import ServerError, getOrdinaryUrl
from auth.constant import HELLO_LOGIN_URL
from auth.new_login import NewLogin, NewWebVPNLogin
from .common_session import CommonLoginSession
from .session_backend import AccessMode
from ..utils import cfg

HELLO_HOST = "hello.xjtu.edu.cn"


def _jwt_system_type(token: str) -> str:
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return str(data.get("systemType") or "yingxin_student_pc")
    except Exception:
        return "yingxin_student_pc"


def _token_from_url(url: str) -> str:
    if not url:
        return ""
    return parse_qs(urlparse(url).query).get("token", [""])[0]


def _is_hello_site(url: str) -> bool:
    """WebVPN 落地 URL 的域名段是密文，不能用 contains('hello.xjtu.edu.cn')。"""
    if HELLO_HOST in url:
        return True
    if "webvpn.xjtu.edu.cn" not in url:
        return False
    try:
        ordinary = getOrdinaryUrl(url)
    except Exception:
        return False
    return bool(ordinary) and HELLO_HOST in ordinary


def _iter_response_urls(response) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: object) -> None:
        text = str(url or "")
        if text and text not in seen:
            seen.add(text)
            urls.append(text)

    add(getattr(response, "url", ""))
    request = getattr(response, "request", None)
    add(getattr(request, "url", ""))
    for item in getattr(response, "history", None) or []:
        add(getattr(item, "url", ""))
        hist_request = getattr(item, "request", None)
        add(getattr(hist_request, "url", ""))
    return urls


def extract_hello_token(response) -> str:
    candidates = _iter_response_urls(response)
    for url in candidates:
        token = _token_from_url(url)
        if token and _is_hello_site(url):
            return token
    for url in candidates:
        token = _token_from_url(url)
        if token and token.count(".") == 2:
            return token
    return ""


class HelloTokenMixin:
    """从 CAS 登录落地 URL 上取出 JWT，而不是再 GET 一次 OAuth 入口。"""

    def postLogin(self, login_response) -> None:
        token = extract_hello_token(login_response)
        if not token:
            raise ServerError(500, "个人信息系统未返回访问令牌")
        session = self.session
        session.access_token = token
        session.system_type = _jwt_system_type(token)
        store = getattr(session, "_store_tokens", None)
        if callable(store):
            store()


class HelloLogin(HelloTokenMixin, NewLogin):
    def __init__(self, session=None, visitor_id=None):
        super().__init__(HELLO_LOGIN_URL, session=session, visitor_id=visitor_id)


class HelloWebVPNLogin(HelloTokenMixin, NewWebVPNLogin):
    """校外走 WebVPN 时复用同一套落地 token 提取。"""

    def __init__(self, session=None, visitor_id=None):
        super().__init__(HELLO_LOGIN_URL, session=session, visitor_id=visitor_id)


class HelloSession(CommonLoginSession):
    """hello.xjtu.edu.cn：落地 URL 上的 JWT，不是 cookie。"""

    site_key = "hello"
    site_name = "学籍档案"
    supports_webvpn = True
    use_webvpn_when_off_campus = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.access_token = ""
        self.system_type = "yingxin_student_pc"

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.access_token = ""
        self.system_type = "yingxin_student_pc"

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.access_token = self.headers.get("access_token", "") or self.headers.get("access-token", "")
        self.system_type = self.headers.get("systemtype", "yingxin_student_pc")

    def _store_tokens(self) -> None:
        self.headers["access-token"] = self.access_token
        self.headers["access_token"] = self.access_token
        self.headers["systemtype"] = self.system_type
        self.headers["synAccessSource"] = "pc"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_class = HelloWebVPNLogin if self.access_mode == AccessMode.WEBVPN else HelloLogin
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: login_class(session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        if not self.access_token:
            raise ServerError(500, "个人信息系统未返回访问令牌")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        return bool(self.access_token)
