from __future__ import annotations

import threading
import time
from abc import ABCMeta, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

import requests
import requests.structures

from .session_backend import AccessMode, SessionBackend

if TYPE_CHECKING:
    from app.utils.account import Account
    from app.utils.mfa import MFAProvider


class CommonLoginSession(metaclass=ABCMeta):
    """
    需要登录的所有网站的 Session 基类，具有登录/重新登录的接口。
    由于会出现无限递归，此类自身不支持自动重新登录，需要外界检查 has_timeout 接口并手动调用登录。
    在本程序的其他模块，统一使用 session 提供的方法登录，没有具体的进度提示。
    """
    # 当前站点的标识符号。子类应当重写这个变量
    site_key = ""
    # 当前站点展示给用户的名称。子类可以重写这个变量
    site_name = ""
    # 站点默认选择的访问方式（是否通过 WebVPN 访问）
    default_access_mode = AccessMode.NORMAL
    # 当前站点是否支持 WebVPN。子类应当重写这个变量
    supports_webvpn = False

    def __init__(self, backend: SessionBackend | None = None, site_key: str | None = None,
                 timeout: int = 15 * 60) -> None:
        """
        初始化一个登录 session
        :param timeout: 在多长时间不发送网络请求后，需要重新登录。
        """
        self.backend = backend or SessionBackend(self.default_access_mode, timeout=timeout)
        self.site_key = site_key or self.site_key or self.__class__.__name__
        # 站点专用 headers。底层 UA 等共享 headers 保存在 backend.session.headers 中。
        self.headers = requests.structures.CaseInsensitiveDict()
        # 超时时间
        self._timeout = timeout
        # 上次发送请求的时间
        self._last_request_time = 0.0
        # 是否已经登录
        self._has_login = False
        self.login_method = None
        # 自身防止同时登录的锁
        self.login_lock = threading.RLock()

    @property
    def access_mode(self) -> AccessMode:
        """返回当前适配器正在使用的访问方式。"""
        return self.backend.access_mode

    @property
    def cookies(self) -> requests.cookies.RequestsCookieJar:
        """返回当前访问方式共享的 cookie jar。"""
        return self.backend.session.cookies

    @property
    def has_login(self) -> bool:
        """
        当前 session 是否已经登录。此属性默认为 False，需要手动设置为 True.
        当前 session 超时后，此属性会被自动设置为 False.
        此属性和 has_timeout 有所区别：has_timeout 在发起请求后便会变为 False，
        因此如果登录到一半被取消，has_timeout 已经从 True 变为 False，但其实现在没有登录成功,
        因此需要额外的标识位。
        如果当前已经超时，那么查询 has_login 时，has_login 会变为 False。
        """
        if self.has_timeout():
            self._has_login = False
        return self._has_login

    @has_login.setter
    def has_login(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise ValueError("has_login should be bool ")

        self._has_login = value
        if value:
            self.backend.has_login = True

    def login(self, username: str, password: str, **kwargs: object) -> None:
        """
        登录指定的网站。
        """
        with self.login_lock:
            self.clear_site_state()
            self._login(username, password, **kwargs)

    @abstractmethod
    def _login(self, username: str, password: str, **kwargs: object) -> None:
        """
        登录。此方法应当被重载，以便实际实现登录的操作。
        """

    def re_login(self, username: str, password: str, **kwargs: object) -> None:
        """
        重新登录指定的网站。
        """
        with self.login_lock:
            self.clear_site_state()
            self._re_login(username, password, **kwargs)

    @abstractmethod
    def _re_login(self, username: str, password: str, **kwargs: object) -> None:
        """
        重新登录。此方法应当被重载，以便实际实现重新登录的操作。
        """

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        """
        重载 request 方法，记录上次请求时间，并增加站点特有的 header
        """
        self.reset_timeout()
        self.backend.reset_timeout()

        request_headers = kwargs.pop("headers", None)
        headers: dict[str, str] = {}
        # 使用公用 headers
        headers.update(self.backend.session.headers)
        # 增加站点特殊要求的 headers
        headers.update(self.headers)
        if request_headers is not None:
            if not isinstance(request_headers, Mapping):
                raise TypeError("headers should be a mapping")
            for key, value in request_headers.items():
                headers[str(key)] = str(value)

        return self.backend.session.request(method, url, headers=headers, **kwargs)

    def get(self, url: str, **kwargs: object) -> requests.Response:
        """发起 GET 请求。"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        """发起 POST 请求。"""
        return self.request("POST", url, **kwargs)

    def set_backend(self, backend: SessionBackend) -> None:
        """切换当前站点适配器使用的共享后端。"""
        self.backend = backend

    def clear_site_state(self) -> None:
        """清理当前站点适配器状态，不清理共享 cookie。"""
        self._has_login = False
        self.headers.clear()
        self.login_method = None

    def clear_backend_cookies(self) -> None:
        """清理当前访问方式共享后端的全部 cookie。"""
        self.backend.clear_cookies()
        self.clear_site_state()

    def get_login_context(self, kwargs: dict[str, object]) -> tuple[Account | None, MFAProvider | None]:
        """
        从登录参数中提取账号和 MFA provider 上下文。
        """
        from app.utils.account import Account

        account_value = kwargs.get("account")
        account = account_value if isinstance(account_value, Account) else None
        provider_value = kwargs.get("mfa_provider")
        provider = cast("MFAProvider | None", provider_value)
        if provider is None and account is not None:
            provider = account.session_manager.mfa_provider
        return account, provider

    def close(self) -> None:
        """关闭当前适配器使用的共享后端。"""
        self.backend.close()

    def has_timeout(self) -> bool:
        """
        检查是否需要重新登录
        """
        return time.time() - self._last_request_time > self._timeout

    def reset_timeout(self) -> None:
        """
        重置超时时间为 self._timeout 那么长之后
        """
        self._last_request_time = time.time()
