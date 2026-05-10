from __future__ import annotations

import enum
import threading
import time

import requests


class AccessMode(enum.Enum):
    """表示底层会话的访问方式。"""

    NORMAL = "normal"
    WEBVPN = "webvpn"


class SessionBackend:
    """同一账号、同一访问方式下共享的底层请求后端。"""

    def __init__(self, access_mode: AccessMode, timeout: int = 15 * 60) -> None:
        """创建一个共享请求后端。"""
        from app.utils.config import cfg

        self.access_mode = access_mode
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": cfg.userAgent.value})
        self.timeout = timeout
        self.last_request_time = 0.0
        self.has_login = False
        self.login_lock = threading.RLock()

    def reset_timeout(self) -> None:
        """刷新后端最近请求时间。"""
        self.last_request_time = time.time()

    def has_timeout(self) -> bool:
        """判断后端登录态是否已经超过本地超时时间。"""
        return time.time() - self.last_request_time > self.timeout

    def clear_cookies(self) -> None:
        """清理当前后端的全部 cookie。"""
        self.session.cookies.clear()
        self.has_login = False

    def close(self) -> None:
        """关闭底层 requests session。"""
        self.session.close()
