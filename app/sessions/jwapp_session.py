from __future__ import annotations

from app.sessions.common_session import CommonLoginSession
from app.utils import cfg
from app.utils.interactive_login import login_with_optional_mfa
from auth.new_login import NewLogin
from jwapp.util import JwappNewLogin


class JwappSession(CommonLoginSession):
    """
    jwapp.xjtu.edu.cn 登录用的 Session
    """
    site_key = "jwapp"
    site_name = "移动教务系统"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        login_util = JwappNewLogin(session=self, visitor_id=str(cfg.loginId.value))
        account, mfa_provider = self.get_login_context(kwargs)
        login_with_optional_mfa(
            login_util,
            username,
            password,
            account,
            mfa_provider,
            account_type=NewLogin.UNDERGRADUATE,
            site_key=self.site_key,
            site_name=self.site_name,
        )

        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        """通过移动教务的通用接口验证站点登录态。"""
        if "Authorization" not in self.headers:
            return False

        response = self.get(
            "https://jwapp.xjtu.edu.cn/api/biz/v410/common/school/time",
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False

        try:
            result = response.json()
        except ValueError:
            return False

        return result.get("code") == 200
