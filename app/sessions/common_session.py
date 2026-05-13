from __future__ import annotations

import threading
import time
from urllib.parse import urlparse
from abc import ABCMeta, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import requests
import requests.structures

from auth import ServerError, is_safety_verify_page
from .session_backend import AccessMode, SessionBackend

if TYPE_CHECKING:
    from app.utils.account import Account
    from app.utils.mfa import MFAProvider
    from app.utils.session_manager import SessionManager


@dataclass(frozen=True)
class LoginContext:
    """
    记录最近一次登录使用的账号上下文，用于登录态失效后的原地恢复。
    """
    username: str
    password: str
    account_uuid: str | None
    kwargs: Mapping[str, object]


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
        self._login_context: LoginContext | None = None
        self._login_depth = 0
        self.session_manager: SessionManager | None = None
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
        if self.has_timeout() or self.backend.has_timeout():
            self._has_login = False
            if self.backend.has_timeout():
                self.backend.has_login = False
        return self._has_login

    @has_login.setter
    def has_login(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise ValueError("has_login should be bool ")

        self._has_login = value
        if value:
            self.backend.has_login = True

    def login(self, username: str, password: str, preferred_access_mode: AccessMode | None = None,
              **kwargs: object) -> None:
        """
        登录指定的网站。
        """
        with self.login_lock:
            self._remember_login_context(username, password, kwargs)
            self.choose_backend(preferred=preferred_access_mode, **kwargs)
            self._ensure_webvpn_backend_login(username, password, **kwargs)
            self.clear_site_state()
            self._run_login(username, password, **kwargs)

    def ensure_login(self, username: str, password: str, force: bool = False,
                     preferred_access_mode: AccessMode | None = None, **kwargs: object) -> bool:
        """
        确保当前业务站点已经具有可用登录态。

        :param username: 登录用户名
        :param password: 登录密码
        :param force: 是否跳过现有状态并强制重新登录
        :param kwargs: 传递给具体登录实现的上下文参数
        :return: 如果本次执行了登录流程则返回 True，否则返回 False
        """
        with self.login_lock:
            self._remember_login_context(username, password, kwargs)
            self.choose_backend(preferred=preferred_access_mode, **kwargs)
            if not force and self.has_login and self.validate_login():
                return False

            self.invalidate_login()
            self._ensure_webvpn_backend_login(username, password, **kwargs)
            self._run_login(username, password, **kwargs)
            return True

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
            self._remember_login_context(username, password, kwargs)
            self.clear_site_state()
            self._run_re_login(username, password, **kwargs)

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
        skip_auth_check = kwargs.pop("_skip_auth_check", False) is True
        skip_webvpn_rewrite = kwargs.pop("_skip_webvpn_rewrite", False) is True
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

        prepared_url = self.prepare_url_for_access_mode(url, skip_webvpn_rewrite=skip_webvpn_rewrite)
        prepared_headers = self.prepare_headers_for_access_mode(headers, skip_webvpn_rewrite=skip_webvpn_rewrite)
        response = self.backend.session.request(method, prepared_url, headers=prepared_headers, **kwargs)
        if skip_auth_check or self._login_depth > 0 or not self.is_auth_failure_response(response):
            return response

        self.invalidate_login()
        return self._retry_request_after_auth_failure(method, url, request_headers, kwargs)

    def get(self, url: str, **kwargs: object) -> requests.Response:
        """发起 GET 请求。"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> requests.Response:
        """发起 POST 请求。"""
        return self.request("POST", url, **kwargs)

    def set_backend(self, backend: SessionBackend) -> None:
        """切换当前站点适配器使用的共享后端。"""
        self.backend = backend

    def choose_backend(self, *, preferred: AccessMode | None = None, **kwargs: object) -> AccessMode:
        """根据统一访问策略选择当前站点适配器使用的后端。"""
        if self.session_manager is None:
            return self.access_mode

        target_mode = self.session_manager.resolve_access_mode(preferred=preferred)
        if target_mode == AccessMode.WEBVPN and not self.supports_webvpn:
            target_mode = AccessMode.NORMAL

        if target_mode != self.access_mode:
            self.set_backend(self.session_manager.get_backend(target_mode))
            self.clear_site_state()
        return target_mode

    def prepare_url_for_access_mode(self, url: str, *, skip_webvpn_rewrite: bool = False) -> str:
        """根据当前访问方式准备实际请求 URL。"""
        if skip_webvpn_rewrite or self.access_mode != AccessMode.WEBVPN:
            return url
        if not self._should_rewrite_to_webvpn(url):
            return url

        from auth import getVPNUrl

        return getVPNUrl(url)

    def prepare_headers_for_access_mode(self, headers: dict[str, str], *,
                                        skip_webvpn_rewrite: bool = False) -> dict[str, str]:
        """根据当前访问方式准备本次请求使用的 headers 副本。"""
        if skip_webvpn_rewrite or self.access_mode != AccessMode.WEBVPN:
            return headers

        prepared = dict(headers)
        referer = prepared.get("Referer") or prepared.get("referer")
        if referer is not None and self._should_rewrite_to_webvpn(referer):
            from auth import getVPNUrl

            rewritten = getVPNUrl(referer)
            if "Referer" in prepared:
                prepared["Referer"] = rewritten
            else:
                prepared["referer"] = rewritten
        return prepared

    def clear_site_state(self) -> None:
        """清理当前站点适配器状态，不清理共享 cookie。"""
        self._has_login = False
        self.headers.clear()
        self.login_method = None

    def invalidate_login(self) -> None:
        """标记当前业务站点登录态已经失效，并清理站点专属状态。"""
        self.clear_site_state()

    def validate_login(self) -> bool:
        """
        验证当前业务站点登录态是否仍然可信。
        子类可以重写该方法，通过访问学校系统需要权限的接口实测是否要重新登录。
        """
        return self.has_login

    def clear_backend_cookies(self) -> None:
        """清理当前访问方式共享后端的全部 cookie。"""
        self.backend.clear_cookies()
        self.clear_site_state()

    def _ensure_webvpn_backend_login(self, username: str, password: str, **kwargs: object) -> None:
        """在 WebVPN 访问方式下确保 WebVPN 后端本身已经登录。"""
        if self.access_mode != AccessMode.WEBVPN or self.session_manager is None:
            return
        account, mfa_provider = self.get_login_context(kwargs)
        self.session_manager.ensure_webvpn_login(
            username,
            password,
            account=account,
            mfa_provider=mfa_provider,
            is_postgraduate=kwargs.get("is_postgraduate") is True,
        )

    @staticmethod
    def _should_rewrite_to_webvpn(url: str) -> bool:
        """判断 URL 是否应当被改写为 WebVPN 地址。"""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        hostname = parsed.hostname or ""
        if hostname == "webvpn.xjtu.edu.cn":
            return False
        return hostname == "xjtu.edu.cn" or hostname.endswith(".xjtu.edu.cn")

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

    def is_auth_failure_response(self, response: requests.Response) -> bool:
        """
        判断一个响应是否表示当前业务站点登录态已经失效。
        判断标准：
        1. 响应的 Content-Type 不是 HTML 或纯文本，且响应内容不以 "<" 开头（排除接口返回的 JSON 等非 HTML 内容）；
        2. 响应内容是安全验证页或统一身份认证登录页。
        子类可以考虑使用该方法辅助重写 validate_login 方法。
        """
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            stripped_text = response.text.lstrip()
            if not stripped_text.startswith("<"):
                return False

        page = response.text
        return is_safety_verify_page(page) or self._is_unified_login_page(page)

    def _remember_login_context(self, username: str, password: str, kwargs: Mapping[str, object]) -> None:
        """保存最近一次登录上下文，供响应兜底恢复使用。"""
        self._login_context = LoginContext(
            username=username,
            password=password,
            account_uuid=self._extract_account_uuid(kwargs),
            kwargs=dict(kwargs),
        )

    def _extract_account_uuid(self, kwargs: Mapping[str, object]) -> str | None:
        """从登录参数中提取账号 UUID。"""
        from app.utils.account import Account

        account_value = kwargs.get("account")
        if isinstance(account_value, Account):
            return account_value.uuid
        return None

    def _current_account_uuid(self) -> str | None:
        """返回应用当前选中账号的 UUID。"""
        from app.utils.account import accounts

        if accounts.current is None:
            return None
        return accounts.current.uuid

    def _ensure_login_context_matches_current_account(self, context: LoginContext) -> None:
        """确认自动重登上下文仍属于当前选中账号。"""
        current_account_uuid = self._current_account_uuid()
        if context.account_uuid is None or current_account_uuid is None:
            return
        if context.account_uuid == current_account_uuid:
            return

        self.invalidate_login()
        raise ServerError(102, "当前业务系统登录态属于此前选中的账号，请重新登录当前账号。")

    def _is_unified_login_page(self, html_content: str) -> bool:
        """判断响应是否为统一身份认证登录页。"""
        has_login_form = 'id="fm1"' in html_content and 'name="execution"' in html_content
        has_login_marker = (
            "login.xjtu.edu.cn" in html_content
            or "cas/login" in html_content
            or "统一身份认证" in html_content
        )
        return has_login_form and has_login_marker

    def _run_login(self, username: str, password: str, **kwargs: object) -> None:
        """在登录保护区内执行具体登录实现。"""
        self._login_depth += 1
        try:
            self._login(username, password, **kwargs)
        finally:
            self._login_depth -= 1

    def _run_re_login(self, username: str, password: str, **kwargs: object) -> None:
        """在登录保护区内执行具体重新登录实现。"""
        self._login_depth += 1
        try:
            self._re_login(username, password, **kwargs)
        finally:
            self._login_depth -= 1

    def _retry_request_after_auth_failure(
            self,
            method: str,
            url: str,
            request_headers: object,
            request_kwargs: dict[str, object]) -> requests.Response:
        """
        在业务请求遇到二次认证页后，尝试重新登录并重放本次请求。
        """
        if self._login_context is None:
            raise ServerError(102, "当前业务系统登录态已失效，需要重新登录。")

        context = self._login_context
        # 确保缓存的账号和当前登录的账户一致，以免误用之前账号的登录态
        # 这一般不会有问题，因为 SessionManager 是每个账户都有一个的，因此每个账户都各自持有每种 session
        # 理论上不会出现登录态被误用到其他账号的情况，但这里多加一个检查以防万一
        self._ensure_login_context_matches_current_account(context)
        # 尝试重新使用 context 静默登录
        self.ensure_login(context.username, context.password, force=True, **dict(context.kwargs))

        retry_kwargs = dict(request_kwargs)
        if request_headers is not None:
            retry_kwargs["headers"] = request_headers
        retry_kwargs["_skip_auth_check"] = True
        retry_response = self.request(method, url, **retry_kwargs)
        if self.is_auth_failure_response(retry_response):
            self.invalidate_login()
            raise ServerError(102, "当前业务系统登录态已失效，需要重新进行安全验证。")
        return retry_response

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
