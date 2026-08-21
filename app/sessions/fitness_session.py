from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import time
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

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

    API_ROOT = "https://tyxylp.xjtu.edu.cn/v3/api.php"
    USER_INFO_URL = f"{API_ROOT}/WpLogin/UserInfo"
    H5_HOME_URL = "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/#/pages/index/index"
    AES_KEY = b"Wet2C8d34f62ndi3"
    AES_IV = b"K6iv85jBD8jgf32D"
    SIGN_SALT = "rDJiNB9j7vD2"
    REQUIRED_LAUNCH_FIELDS = (
        "uid", "token", "school_id", "term_id", "student_num", "card_id", "user_type",
    )
    SESSION_FIELDS = ("uid", "token", "school_id", "term_id", "student_num", "card_id", "nonce")
    ROLE_BY_USER_TYPE = {"1": 2, "2": 1, "3": 3}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.referer_url = self.H5_HOME_URL
        self._fitness_session: dict[str, object] = {}

    def clear_site_state(self) -> None:
        super().clear_site_state()
        self.referer_url = self.H5_HOME_URL
        self._fitness_session = {}

    def restore_site_snapshot(self, snapshot) -> None:
        super().restore_site_snapshot(snapshot)
        self.referer_url = self.headers.get("X-Fitness-Referer", self.H5_HOME_URL)

    def _extract_launch_session(self, url: str) -> tuple[dict[str, object], str]:
        callback = urlparse(url)
        if callback.hostname != "tyxylp.xjtu.edu.cn":
            raise ServerError(102, "体测登录回调异常")

        fragment_path, separator, fragment_query = callback.fragment.partition("?")
        if not separator:
            raise ServerError(102, "体测登录回调缺少会话参数")
        params = {
            key: values[0]
            for key, values in parse_qs(fragment_query, keep_blank_values=True).items()
            if values
        }
        if any(not params.get(key) for key in self.REQUIRED_LAUNCH_FIELDS):
            raise ServerError(102, "体测登录回调缺少会话参数")

        role = self.ROLE_BY_USER_TYPE.get(params["user_type"])
        if role is None:
            raise ServerError(102, "体测登录回调用户类型异常")
        session: dict[str, object] = {
            key: params[key]
            for key in self.SESSION_FIELDS
            if params.get(key)
        }
        session.update({"ostype": "5", "role": role})
        referer = callback._replace(query="", fragment=fragment_path).geturl()
        return session, referer

    @classmethod
    def _encrypt_payload(cls, payload: Mapping[str, object]) -> str:
        plaintext = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        cipher = AES.new(cls.AES_KEY, AES.MODE_CBC, cls.AES_IV)
        encrypted = cipher.encrypt(pad(plaintext, AES.block_size))
        return base64.b64encode(encrypted).decode("ascii")

    @classmethod
    def _decrypt_payload(cls, value: object) -> object | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            encrypted = base64.b64decode("".join(value.split()), validate=True)
            cipher = AES.new(cls.AES_KEY, AES.MODE_CBC, cls.AES_IV)
            plaintext = unpad(cipher.decrypt(encrypted), AES.block_size)
            return json.loads(plaintext.decode("utf-8"))
        except (binascii.Error, UnicodeError, ValueError):
            return None

    def _build_api_payload(self, data: Mapping[str, object]) -> dict[str, object]:
        timestamp = int(time.time())
        nonce = f"{secrets.randbelow(1_000_000):06d}"
        payload: dict[str, object] = {
            "uid": self._fitness_session.get("uid", ""),
            "token": self._fitness_session.get("token", ""),
            "school_id": self._fitness_session.get("school_id", ""),
            "term_id": self._fitness_session.get("term_id", ""),
            "class_id": 0,
            "student_num": self._fitness_session.get("student_num", ""),
            "card_id": self._fitness_session.get("card_id", ""),
            "timestamp": timestamp,
            "version": 1,
            "nonce": nonce,
            "ostype": 5,
        }
        payload.update(self._fitness_session)
        payload.update(data)
        payload["timestamp"] = timestamp
        payload["nonce"] = nonce
        sign_source = "".join(f"{key}{payload[key]}" for key in sorted(payload)) + self.SIGN_SALT
        payload["sign"] = hashlib.md5(sign_source.encode("utf-8")).hexdigest()
        return payload

    def _request_user_info(self, *, timeout: int) -> Mapping[str, object] | None:
        if not self._fitness_session:
            return None
        payload = self._build_api_payload({"uid": self._fitness_session.get("uid", "")})
        response = self.post(
            self.USER_INFO_URL,
            data={"ostype": 5, "data": self._encrypt_payload(payload)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://tyxylp.xjtu.edu.cn",
                "Referer": self.referer_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
            _skip_auth_check=True,
        )
        if not response.ok or self.is_auth_failure_response(response):
            return None
        try:
            response_payload = response.json()
        except (TypeError, ValueError):
            response_payload = response.text

        if isinstance(response_payload, str):
            user_info = self._decrypt_payload(response_payload)
        elif isinstance(response_payload, Mapping) and response_payload.get("status") == 1:
            user_info = self._decrypt_payload(response_payload.get("data"))
        else:
            return None
        return user_info if isinstance(user_info, Mapping) and user_info else None

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
        self._fitness_session, self.referer_url = self._extract_launch_session(response.url)
        self.headers["X-Fitness-Referer"] = self.referer_url
        try:
            user_info = self._request_user_info(timeout=15)
        except Exception:
            self.clear_site_state()
            raise
        if user_info is None:
            self.clear_site_state()
            raise ServerError(102, "体测会话初始化失败")
        self.reset_timeout()
        self.has_login = True

    _re_login = _login

    def validate_login(self) -> bool:
        try:
            return self._request_user_info(timeout=10) is not None
        except requests.RequestException:
            return False
