from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import requests

from app.sessions.session_backend import AccessMode, SessionBackend

if TYPE_CHECKING:
    from app.utils.account import Account
    from app.sessions.common_session import CommonLoginSession
    from app.utils.mfa import MFAProvider


class SessionManager:
    """
    SessionManager 保存此应用程序访问的所有网站的 session。
    此类是为了防止多个模块创建针对相同网站的登录 session，然后相互踢出对方登录的情况出现
    程序使用的任何需要登录的网站的 session 都应当被保存在此处。
    """
    # 类变量，用于存放全局注册的 session 类
    sessions: dict[str, type[CommonLoginSession]] = {}

    def __init__(self) -> None:
        """
        创建一个 session 管理器
        """
        self.sessions: dict[str, type[CommonLoginSession]] = {}
        self.instances: dict[str, CommonLoginSession | None] = {}
        self.backends = {
            AccessMode.NORMAL: SessionBackend(AccessMode.NORMAL),
            AccessMode.WEBVPN: SessionBackend(AccessMode.WEBVPN),
        }
        self.mfa_provider: MFAProvider | None = None
        self._access_probe_result: AccessMode | None = None
        self._access_probe_time = 0.0
        self._access_probe_lock = threading.RLock()

    def register(self, class_: type[CommonLoginSession], name: str, allow_override: bool = True) -> None:
        """
        注册一个 session 类。注册后，就可以通过 get_session 方法获得这个 session 类的实例。
        :param allow_override: 是否允许覆盖同名已经注册的 session
        :param class_: 需要注册的 session 类。注意，不要传入类的实例
        :param name: 此类注册的名称
        """
        if not allow_override and name in self.sessions:
            raise ValueError(f"session {name} already exists")

        self.sessions[name] = class_
        self.instances[name] = None

    @classmethod
    def global_register(cls, class_: type[CommonLoginSession], name: str, allow_override: bool = True) -> None:
        """
        全局注册一个 session 类。注册后，可以在此类的任何一个实例中访问此 session 类。
        不要在全局级别和实例级别同时注册同一个 session 类，否则可能出现诡异的问题。
        :param allow_override: 是否允许覆盖同名已经注册的 session
        :param class_: 需要注册的 session 类。注意，不要传入类的实例
        :param name: 此类注册的名称
        """
        if not allow_override and name in cls.sessions:
            raise ValueError(f"session {name} already exists")

        cls.sessions[name] = class_

    def exists(self, name: str) -> bool:
        """
        判断一个 session 是否已经注册
        :param name: session 的名称
        """
        return name in self.sessions or name in self.__class__.sessions

    def instance_exists(self, name: str) -> bool:
        """
        判断一个 session 实例是否已经创建
        :param name: session 的名称
        """
        return name in self.instances and self.instances[name] is not None

    def rename(self, old_name: str, new_name: str, allow_override: bool = True) -> None:
        """
        重命名一个已经注册的 session 类的名称。请注意，全局注册的 session 名称无法被修改。
        :param old_name: 类注册时填入的名称
        :param new_name: 新的名称
        :param allow_override: 是否允许覆盖同名已经注册的 session
        """
        if old_name not in self.sessions:
            raise ValueError(f"session {old_name} not found")
        if not allow_override and new_name in self.sessions:
            raise ValueError(f"session {new_name} already exists")

        self.sessions[new_name] = self.sessions.pop(old_name)
        self.instances[new_name] = self.instances.pop(old_name)

    def get_session(self, name: str) -> CommonLoginSession:
        """
        获取一个名称为 name 的 session 类的实例
        :param name: session 的名称
        """
        if name not in self.sessions and name not in self.__class__.sessions:
            raise ValueError(f"session {name} not found")
        # 由于此类的类变量和成员变量不互通，因此需要判断从类变量还是成员变量中取出 session 类
        if name not in self.instances or self.instances[name] is None:
            if name in self.sessions:
                self.instances[name] = self._create_session(self.sessions[name])
            else:
                self.instances[name] = self._create_session(self.__class__.sessions[name])
        return self.instances[name]

    def get_backend(self, access_mode: AccessMode) -> SessionBackend:
        """获取指定访问方式对应的共享后端。"""
        return self.backends[access_mode]

    def resolve_access_mode(self, *, force_refresh: bool = False,
                            preferred: AccessMode | None = None) -> AccessMode:
        """根据用户设置和网络探测结果解析本次校内系统访问方式。"""
        from app.utils.config import cfg

        if preferred is not None:
            return preferred

        policy = cfg.campusAccessPolicy.value
        if policy == cfg.NetworkAccessPolicy.DIRECT:
            return AccessMode.NORMAL
        if policy == cfg.NetworkAccessPolicy.WEBVPN:
            return AccessMode.WEBVPN

        with self._access_probe_lock:
            now = time.time()
            if not force_refresh and self._access_probe_result is not None and now - self._access_probe_time < 5 * 60:
                return self._access_probe_result

            mode = AccessMode.NORMAL if self.can_reach_campus_network() else AccessMode.WEBVPN
            self._access_probe_result = mode
            self._access_probe_time = now
            return mode

    def can_reach_campus_network(self, *, timeout: float = 10.0) -> bool:
        """通过访问教务系统首页判断当前网络是否可以直连校内系统。"""
        try:
            response = requests.get("https://jwxt.xjtu.edu.cn/", timeout=timeout)
            response.close()
            return True
        except requests.RequestException:
            return False

    def start_background_access_probe(self) -> None:
        """在自动访问模式下后台预热当前账号的网络探测结果。"""
        from app.utils.config import cfg
        from app.utils.log import logger

        if cfg.campusAccessPolicy.value != cfg.NetworkAccessPolicy.AUTO:
            return

        def worker() -> None:
            try:
                mode = self.resolve_access_mode(force_refresh=True)
                logger.info("校内系统访问模式自动探测完成：%s", mode.value)
            except Exception:
                logger.exception("校内系统访问模式自动探测失败")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def ensure_webvpn_login(self, username: str, password: str, *,
                            account: Account | None = None,
                            mfa_provider: MFAProvider | None = None,
                            is_postgraduate: bool = False) -> None:
        """确保当前账号的 WebVPN 后端已经登录 WebVPN 本身。"""
        from app.utils.config import cfg
        from app.utils.interactive_login import login_with_optional_mfa
        from auth import WEBVPN_LOGIN_URL
        from auth.new_login import NewLogin

        webvpn_backend = self.backends[AccessMode.WEBVPN]
        with webvpn_backend.login_lock:
            if webvpn_backend.has_timeout():
                webvpn_backend.has_login = False
            if webvpn_backend.has_login:
                return

            account_type = NewLogin.POSTGRADUATE if self._is_postgraduate_account(account, is_postgraduate) else NewLogin.UNDERGRADUATE
            login_util = NewLogin(WEBVPN_LOGIN_URL, session=webvpn_backend.session, visitor_id=str(cfg.loginId.value))
            login_with_optional_mfa(
                login_util,
                username,
                password,
                account,
                mfa_provider or self.mfa_provider,
                account_type=account_type,
                site_key="webvpn",
                site_name="WebVPN",
            )
            webvpn_backend.has_login = True
            webvpn_backend.reset_timeout()

    @staticmethod
    def _is_postgraduate_account(account: Account | None, is_postgraduate: bool) -> bool:
        """判断当前登录上下文是否应使用研究生身份。"""
        if is_postgraduate:
            return True
        if account is None:
            return False
        return getattr(account, "type", None) == getattr(account, "POSTGRADUATE", None)

    def set_mfa_provider(self, provider: MFAProvider | None) -> None:
        """
        设置当前账号会话管理器使用的 MFA 交互提供者。
        """
        self.mfa_provider = provider

    def _create_session(self, class_: type[CommonLoginSession]) -> CommonLoginSession:
        """创建一个站点 Session 适配器实例。"""
        backend = self.backends[class_.default_access_mode]
        session = class_(backend=backend)
        session.session_manager = self
        return session
