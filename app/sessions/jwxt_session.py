from __future__ import annotations

from auth.constant import JWXT_LOGIN_URL
from auth.new_login import NewLogin
from app.utils.interactive_login import login_with_optional_mfa
from .common_session import CommonLoginSession
from ..utils import cfg


class JWXTSession(CommonLoginSession):
    """
    ehall.xjtu.edu.cn 登录用的 Session
    """
    site_key = "jwxt"
    site_name = "本科教务系统"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_util = NewLogin(JWXT_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过教务系统当前用户接口验证站点登录态。"""
        response = self.get(
            "https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/api/home/currentUser.do",
            headers={
                "Referer": "https://jwxt.xjtu.edu.cn/jwapp/sys/homeapp/home/index.html?av=&contextPath=/jwapp"
            },
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False

        try:
            result = response.json()
        except ValueError:
            return False

        return result.get("code") == "0" and isinstance(result.get("datas"), dict)
