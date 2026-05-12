from __future__ import annotations

from typing import TYPE_CHECKING

from app.sessions.session_backend import AccessMode, SessionBackend

if TYPE_CHECKING:
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

    def set_mfa_provider(self, provider: MFAProvider | None) -> None:
        """
        设置当前账号会话管理器使用的 MFA 交互提供者。
        """
        self.mfa_provider = provider

    def _create_session(self, class_: type[CommonLoginSession]) -> CommonLoginSession:
        """创建一个站点 Session 适配器实例。"""
        backend = self.backends[class_.default_access_mode]
        if class_.supports_webvpn:
            return class_(backend=backend, webvpn_backend=self.backends[AccessMode.WEBVPN])
        return class_(backend=backend)
