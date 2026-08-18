from __future__ import annotations

import re
from urllib.parse import urlparse

import requests


LOGOUT_URL_RE = re.compile(r'var\s+logoutUrl\s*=\s*"([^"]+)"')
JS_UNICODE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
ALLOWED_HOSTS = {"jiaocai.lib.xjtu.edu.cn", "jiaocai1.lib.xjtu.edu.cn", "login.xjtu.edu.cn"}
MAX_HOPS = 5
MAX_ROUNDS = 3


def needs_login(body: str) -> bool:
    return bool(LOGOUT_URL_RE.search(body))


def unescape_js(value: str) -> str:
    value = JS_UNICODE_RE.sub(lambda match: chr(int(match.group(1), 16)), value)
    return value.replace("\\/", "/").replace('\\"', '"')


def next_hop(body: str) -> str | None:
    match = LOGOUT_URL_RE.search(body)
    if not match:
        return None
    url = unescape_js(match.group(1))
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        return None
    return url


def follow_login_chain(session: requests.Session, start_page: str) -> bool:
    page = start_page
    seen: set[str] = set()
    for _ in range(MAX_HOPS):
        nxt = next_hop(page)
        if not nxt:
            return True
        if nxt in seen:
            return False
        seen.add(nxt)
        try:
            page = session.get(nxt, timeout=20).text
        except requests.RequestException:
            return False
    return False


def decode_smart(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        return content.decode("gb18030", errors="replace")
    return text
