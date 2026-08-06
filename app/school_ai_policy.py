"""Shared, Qt-independent policy for the official Jiaoxiaozhi browser."""

from __future__ import annotations

from urllib.parse import urlparse, urlsplit, urlunsplit


JIAOXIAOZHI_URL = "https://agent.xjtu.edu.cn/"
JIAOXIAOZHI_OFF_CAMPUS_URL = "https://agent.xjtu.edu.cn/a403.htm"
# XJTU's public documentation for services hosted on ai.xjtu.edu.cn directs
# off-campus users to the client-based SSLVPN.  The repository's generic
# WebVPN URL transformer is intentionally not used here: the transformed AI
# platform URL currently receives WebVPN's "no permission" response.
XJTU_SSLVPN_URL = "https://sslvpn.xjtu.edu.cn/"

_BROWSER_NETWORK_ERROR_MARKERS = (
    "checking the proxy",
    "checking the firewall",
    "this site can't be reached",
    "this site can’t be reached",
    "err_connection_",
    "err_ssl_",
    "refused to connect",
    "连接被重置",
    "无法访问此网站",
    "网络错误",
)


def looks_like_browser_network_error(value: str) -> bool:
    normalized = " ".join(str(value or "").lower().split())
    return any(marker in normalized for marker in _BROWSER_NETWORK_ERROR_MARKERS)


def is_allowed_school_url_text(value: str) -> bool:
    try:
        parsed = urlparse(str(value))
        port = parsed.port
    except (TypeError, ValueError):
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme.lower() == "https"
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and (host == "xjtu.edu.cn" or host.endswith(".xjtu.edu.cn"))
    )


def upgrade_school_url_text(value: str) -> str:
    """Upgrade a credential-free plain-HTTP XJTU main-frame URL to HTTPS."""

    try:
        parsed = urlsplit(str(value))
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "http"
        or parsed.username
        or parsed.password
        or port not in {None, 80}
        or not (host == "xjtu.edu.cn" or host.endswith(".xjtu.edu.cn"))
    ):
        return ""
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, parsed.fragment))


def safe_display_url(value: str) -> str:
    """Remove credentials, query and fragment before displaying a URL."""

    try:
        parsed = urlsplit(str(value))
        port_value = parsed.port
    except (TypeError, ValueError):
        return ""
    if not parsed.hostname:
        return ""
    port = f":{port_value}" if port_value and port_value != 443 else ""
    return urlunsplit((parsed.scheme, parsed.hostname + port, parsed.path, "", ""))
