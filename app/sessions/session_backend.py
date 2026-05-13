from __future__ import annotations

import enum
from http.cookiejar import LWPCookieJar
import threading
import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from app.utils.session_persistence import BackendSnapshot


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
        self.session.cookies = LWPCookieJar()
        self.session.headers.update({"User-Agent": cfg.userAgent.value})
        self.timeout = timeout
        self.last_request_time = 0.0
        self.has_login = False
        self.restored_auth_candidate = False
        self.login_lock = threading.RLock()

    def reset_timeout(self) -> None:
        """刷新后端最近请求时间。"""
        self.last_request_time = time.time()

    def has_timeout(self) -> bool:
        """判断后端登录态是否已经超过本地超时时间。"""
        return time.time() - self.last_request_time > self.timeout

    def clear_cookies(self) -> None:
        """清理当前后端的全部 cookie。"""
        self.clear_auth_state()

    def clear_auth_state(self) -> None:
        """清理当前后端的认证状态。"""
        self.session.cookies.clear()
        self.has_login = False
        self.restored_auth_candidate = False

    def to_snapshot(self) -> BackendSnapshot:
        """导出当前后端的认证快照。"""
        from app.utils.config import cfg
        from app.utils.session_persistence import BackendSnapshot, cookie_jar_to_lwp_text

        cookie_jar = self.session.cookies
        if not isinstance(cookie_jar, LWPCookieJar):
            raise TypeError("session.cookies should be LWPCookieJar")
        return BackendSnapshot(
            access_mode=self.access_mode.value,
            cookie_lwp_text=cookie_jar_to_lwp_text(cookie_jar),
            cookie_file=None,
            user_agent=str(cfg.userAgent.value),
            login_id=str(cfg.loginId.value),
            saved_at=time.time(),
        )

    def restore_snapshot(self, snapshot: BackendSnapshot) -> bool:
        """从认证快照恢复当前后端，返回快照是否可安全使用。"""
        from app.utils.config import cfg
        from app.utils.session_persistence import lwp_text_to_cookie_jar

        if snapshot.user_agent != str(cfg.userAgent.value) or snapshot.login_id != str(cfg.loginId.value):
            self.clear_auth_state()
            return False

        cookie_jar = lwp_text_to_cookie_jar(snapshot.cookie_lwp_text)
        if cookie_jar is None:
            self.clear_auth_state()
            return False

        self.session.cookies = cookie_jar
        if len(list(self.session.cookies)) > 0:
            self.mark_restored_candidate()
        else:
            self.clear_auth_state()
        return True

    def mark_restored_candidate(self) -> None:
        """将当前后端标记为待验证恢复态。"""
        self.has_login = True
        self.restored_auth_candidate = True
        self.reset_timeout()

    def mark_login_validated(self) -> None:
        """将当前后端标记为已经验证的登录态。"""
        self.has_login = True
        self.restored_auth_candidate = False
        self.reset_timeout()

    def close(self) -> None:
        """关闭底层 requests session。"""
        self.session.close()
