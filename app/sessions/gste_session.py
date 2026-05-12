from __future__ import annotations

import enum

from app.sessions.common_session import CommonLoginSession
from app.sessions.session_backend import AccessMode, SessionBackend
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from auth import WEBVPN_LOGIN_URL, GSTE_LOGIN_URL, getVPNUrl
from auth.new_login import NewLogin, NewWebVPNLogin


class GSTESession(CommonLoginSession):
    """
    gste.xjtu.edu.cn 登录用的 Session
    此网站要求校园网内访问，因此校外必须采用 WebVPN 访问
    """
    site_key = "gste"
    site_name = "研究生评教系统"
    supports_webvpn = True

    class LoginMethod(enum.Enum):
        NORMAL = 0
        WEBVPN = 1

    def __init__(self, backend: SessionBackend | None = None, webvpn_backend: SessionBackend | None = None,
                 timeout: int = 15 * 60) -> None:
        super().__init__(backend=backend, timeout=timeout)
        self.normal_backend = self.backend
        self.webvpn_backend = webvpn_backend or SessionBackend(AccessMode.WEBVPN, timeout=timeout)

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.set_backend(self.normal_backend)
        login_util = NewLogin(GSTE_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            account_type=NewLogin.POSTGRADUATE,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.login_method = self.LoginMethod.NORMAL

        self.reset_timeout()
        self.has_login = True

    def webvpn_login(self, username: str, password: str, **kwargs: object) -> None:
        """通过 WebVPN 登录研究生评教系统。"""
        # 目前 WebVPN 访问分为两个步骤
        # 1. 登录 WebVPN 自身，此时采用不经过 WebVPN 中介的接口
        # 2. 登录 WebVPN 之后，再登录一次目标网站。此时采用经过 WebVPN 中介的接口
        with self.login_lock:
            self.clear_site_state()
            self.set_backend(self.webvpn_backend)
            account, mfa_provider = self.get_login_context(kwargs)

            with self.webvpn_backend.login_lock:
                if self.webvpn_backend.has_timeout():
                    self.webvpn_backend.has_login = False
                if not self.webvpn_backend.has_login:
                    login_util = NewLogin(WEBVPN_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
                    login_with_optional_mfa(
                        login_util,
                        username,
                        password,
                        account,
                        mfa_provider,
                        account_type=NewLogin.POSTGRADUATE,
                        site_key="webvpn",
                        site_name="WebVPN",
                    )
                    self.webvpn_backend.has_login = True

            gste_login_util = NewWebVPNLogin(GSTE_LOGIN_URL, self, visitor_id=str(cfg.loginId.value))
            login_with_optional_mfa(
                gste_login_util,
                username,
                password,
                account,
                mfa_provider,
                account_type=NewLogin.POSTGRADUATE,
                site_key=self.site_key,
                site_name=self.site_name,
            )

            self.login_method = self.LoginMethod.WEBVPN

            self.reset_timeout()
            self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过研究生评教问卷列表页验证站点登录态。"""
        url = "http://gste.xjtu.edu.cn/app/sshd4Stu/list.do"
        if self.login_method == self.LoginMethod.WEBVPN:
            url = getVPNUrl(url)

        response = self.get(url, timeout=10, _skip_auth_check=True)
        if not response.ok or self.is_auth_failure_response(response):
            return False

        page = response.text
        return "sshd4Stu" in page or "questionnaire" in page or "评教" in page or response.url.startswith(url)
