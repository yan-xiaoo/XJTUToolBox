from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from auth import ServerError
from auth.constant import FITNESS_LOGIN_URL
from auth.new_login import NewLogin
from .common_session import CommonLoginSession
from ..utils import cfg


class FitnessSession(CommonLoginSession):
    """tyxylp.xjtu.edu.cn 体测查询，直连。"""

    site_key = "fitness"
    site_name = "体测查询"
    supports_webvpn = False
    use_webvpn_when_off_campus = False

    API_ROOT = "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/public/index.php/index"
    H5_HOME_URL = "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/#/pages/index/index"
    CHECK_LOGIN_FIELDS = (
        "timestamp", "nonce", "course_id", "uid", "card_id", "login_type",
        "type", "school_id", "student_num", "user_type", "token", "sign", "term_id", "id",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.referer_url = self.H5_HOME_URL

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.referer_url = self.H5_HOME_URL

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.referer_url = self.headers.get("X-Fitness-Referer", self.H5_HOME_URL)

    def _login(self, username: str, password: str, **kwargs: object) -> None:
        self.perform_cas_login(
            username,
            password,
            kwargs=kwargs,
            password_login_factory=lambda: NewLogin(
                FITNESS_LOGIN_URL, session=self, visitor_id=str(cfg.loginId.value)
            ),
            qrcode_login_factory=None,
            allow_qrcode_login=False,
        )
        response = self.get(FITNESS_LOGIN_URL, allow_redirects=True, timeout=20, _skip_auth_check=True)
        if "tyxylp.xjtu.edu.cn" not in response.url:
            raise ServerError(102, "体测登录回调异常")
        self.referer_url = response.url or self.H5_HOME_URL
        self.headers["X-Fitness-Referer"] = self.referer_url
        params = {key: parse_qs(urlparse(response.url).query).get(key, [""])[0] for key in self.CHECK_LOGIN_FIELDS}
        if params.get("token") and params.get("sign"):
            check = self.post(
                f"{self.API_ROOT}/Index/checkLogin",
                data=params,
                headers={
                    "Origin": "https://tyxylp.xjtu.edu.cn",
                    "Referer": self.referer_url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
                _skip_auth_check=True,
            )
            try:
                ok = check.json().get("status") == 1
            except ValueError:
                ok = False
            if not check.ok or not ok:
                raise ServerError(102, "体测会话初始化失败")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        response = self.post(
            f"{self.API_ROOT}/fitness/fitnessYear",
            data={"from": "1"},
            headers={
                "Origin": "https://tyxylp.xjtu.edu.cn",
                "Referer": self.referer_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=10,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return False
        try:
            return response.json().get("status") == 1
        except ValueError:
            return False
