"""西交学生智慧社区 ss.xjtu.edu.cn（活动报名，金智 EMAP），直连。"""

from __future__ import annotations

import json
import re

import requests

from auth import ServerError
from auth.new_login import NewLogin
from auth.new_qrcode_login import NewQRCodeLogin
from ss.activity import APP_BASE, APP_INDEX, APP_NAME, DEFAULT_APP_ID, HOST, PUB_BASE
from .common_session import CommonLoginSession
from ..utils import cfg

_APP_ID_IN_PAGE = re.compile(r'APPID\s*:\s*"(\d+)"')


class SsSession(CommonLoginSession):
    """
    从应用首页进，让 ss 自己发起 CAS OAuth（client_id=1707）：直接从 authorize 进的话，
    ss 收到不是自己发起的 code 会重走授权，最后跳回用过的 code → 404。
    登录后还要像页面脚本那样调 getSelRoleConfig + getMenuInfo 把角色写进会话，
    否则报名、我的报名等要身份的接口一律 403。
    """

    site_key = "ss"
    site_name = "智慧社区"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    def _post_emap(self, url: str, data: dict, *, timeout: int = 15) -> bool:
        """EMAP 表单 data=<JSON>；回 JSON 且 code 为 0 才算成功（403、登录页、「未获取到角色」都是 False）。"""
        response = self.post(
            url,
            data={"data": json.dumps(data, ensure_ascii=False, separators=(",", ":"))},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": APP_INDEX},
            timeout=timeout,
            _skip_auth_check=True,
        )
        if response.status_code != 200 or not response.url.startswith(f"https://{HOST}/"):
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        return isinstance(payload, dict) and str(payload.get("code")) == "0"

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(APP_INDEX, session=self, visitor_id=str(cfg.loginId.value)),
            qrcode_login_factory=lambda: NewQRCodeLogin(APP_INDEX, session=self, visitor_id=str(cfg.loginId.value)),
            allow_qrcode_login=kwargs.get("allow_qrcode_login") is not False,
        )
        page = self.get(APP_INDEX, allow_redirects=True, timeout=20, _skip_auth_check=True)
        if not page.url.startswith(f"https://{HOST}/") or self.is_auth_failure_response(page):
            raise ServerError(102, "智慧社区登录没有完成，请重新登录")
        match = _APP_ID_IN_PAGE.search(page.text)
        app = {"APPID": match[1] if match else DEFAULT_APP_ID, "APPNAME": APP_NAME}
        # 页面脚本 spriteFrame.js 启动时的两步：先取角色配置，再取菜单——后者把默认角色写进会话
        self._post_emap(f"{PUB_BASE}/MobileCommon/getSelRoleConfig.do", app)
        if not self._post_emap(f"{PUB_BASE}/MobileCommon/getMenuInfo.do", app):
            raise ServerError(1, "智慧社区没有分配到身份，请稍后重试")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def is_auth_failure_response(self, response: requests.Response) -> bool:
        """会话失效时 Controller 接口被 302 到 CAS，或直接回一张 HTML 页。"""
        if super().is_auth_failure_response(response):
            return True
        path = requests.utils.urlparse(response.url).path
        return (
            path.endswith(".do")
            and "Controller" in path
            and "html" in response.headers.get("Content-Type", "").lower()
        )

    def validate_login(self) -> bool:
        """首页匿名或未选角色时也是 200，探活必须打一个要身份的接口。"""
        try:
            return self._post_emap(
                f"{APP_BASE}/myInfoController/getWdbmInfo.do",
                {"PAGENUM": 1, "PAGESIZE": 1, "querySetting": "[]"},
                timeout=10,
            )
        except requests.RequestException:
            return False
