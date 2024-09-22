import time
from abc import abstractmethod, ABCMeta
from fake_useragent import UserAgent

import requests


_ua = UserAgent(platforms=['pc'])


class CommonLoginSession(requests.Session, metaclass=ABCMeta):
    """
    需要登录的所有网站的 Session 基类，具有登录/重新登录的接口。
    由于会出现无限递归，此类自身不支持自动重新登录，需要外界检查 has_timeout 接口并手动调用登录。
    在本程序的其他模块，为了在登录时给用户进度提示，统一采用如下方法：
    - 第一次获得 session 时，检查其是否已经登录，如果未登录，则更改进度提示并手动调用 login 方法。
    - 之后运行时，不再检查是否已经登录，依靠本类的功能实现重新登录。
    """
    def __init__(self, timeout=15*60):
        """
        初始化一个登录 session
        :param timeout: 在多长时间不发送网络请求后，需要重新登录。
        """
        super().__init__()
        # 设置 UA
        self.headers.update({"User-Agent": _ua.random})
        # 超时时间
        self._timeout = timeout
        # 上次发送请求的时间
        self._last_request_time = 0
        # 是否已经登录
        self._has_login = False

    @property
    def has_login(self):
        """
        当前 session 是否已经登录。此属性默认为 False，需要手动设置为 True.
        当前 session 超时后，此属性会被自动设置为 False.
        此属性和 has_timeout 有所区别：has_timeout 在发起请求后便会变为 False，
        因此如果登录到一半被取消，has_timeout 已经从 True 变为 False，但其实现在没有登录成功,
        因此需要额外的标识位。
        """
        return self._has_login

    @has_login.setter
    def has_login(self, value):
        if not isinstance(value, bool):
            raise ValueError("has_login should be bool ")

        self._has_login = value

    @abstractmethod
    def login(self, username, password):
        """
        登录。此方法应当被重载，实现登录的操作。
        """

    @abstractmethod
    def reLogin(self, username, password):
        """
        重新登录。此方法应当被重载，实现重新登录的操作。
        """

    def request(self, method, url, *args, **kwargs):
        """
        重载 request 方法，记录上次请求时间
        """
        self.reset_timeout()
        return super().request(method, url, *args, **kwargs)

    def has_timeout(self) -> bool:
        """
        检查是否需要重新登录
        """
        if time.time() - self._last_request_time > self._timeout:
            return True
        return False

    def reset_timeout(self):
        """
        重置超时时间为 self._timeout 那么长之后
        """
        self._last_request_time = time.time()
