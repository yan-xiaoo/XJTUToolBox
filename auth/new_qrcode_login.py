from __future__ import annotations

import enum
import json
import re
import time
from dataclasses import dataclass
from typing import Optional, Union

import requests

from .new_login import LoginState, NewLogin, NewWebVPNLogin
from .util import ServerError


def extract_global_config_bool(html_content: str, key: str, default: bool = False) -> bool:
    """
    从登录页 globalConfig 中提取布尔配置。
    """
    match = re.search(r'globalConfig\s*=\s*eval\(\'\(\'\s*\+\s*"(.*?)"\s*\+\s*\'\)\'\s*\);',
                      html_content, re.DOTALL)
    if not match:
        return default

    json_text = match.group(1).encode("utf-8").decode("unicode_escape")
    try:
        config = json.loads(json_text)
    except ValueError:
        return default
    if not isinstance(config, dict):
        return default

    value = config.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return default


class QRCodeLoginStatus(enum.Enum):
    """
    二维码登录轮询状态。
    """
    WAITING = "waiting"
    SCANNED = "scanned"
    AUTHORIZED = "authorized"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass(frozen=True)
class QRCodeCometResult:
    """
    一次二维码轮询返回的结构化结果。
    """
    status: QRCodeLoginStatus
    message: str
    user_id: str = ""
    state_key: str = ""


class QRCodeLoginMixin:
    """
    为统一认证登录类增加二维码扫码登录能力。
    """
    QRCODE_URL = "https://login.xjtu.edu.cn/cas/qr/qrcode"
    COMET_URL = "https://login.xjtu.edu.cn/cas/qr/comet"

    def __init__(self, *args: object, **kwargs: object) -> None:
        """
        初始化底层登录类并安装二维码登录状态。
        """
        super().__init__(*args, **kwargs)
        self._init_qrcode_login()

    def _init_qrcode_login(self) -> None:
        """
        初始化二维码登录状态。
        """
        self._qr_user_id: str | None = None
        self._qr_state_key: str | None = None
        self.mfa_qrcode_login_enabled = extract_global_config_bool(
            self.initial_login_page_html,
            "mfaQrCodeLoginEnabled",
            default=False,
        )

    def get_qrcode_image(self) -> bytes:
        """
        请求一张新的二维码图片。
        """
        response = self._get(
            self.QRCODE_URL,
            params={"r": str(int(time.time() * 1000))},
            headers={"Referer": self.post_url},
        )
        response.raise_for_status()
        return response.content

    def poll_qrcode_status(self) -> QRCodeCometResult:
        """
        轮询二维码扫码状态。
        """
        response = self._post(
            self.COMET_URL,
            headers={"Referer": self.post_url},
            timeout=1,
        )
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise ServerError(500, "服务器返回了无法解析的二维码状态。") from exc

        if not isinstance(result, dict):
            return QRCodeCometResult(QRCodeLoginStatus.ERROR, "二维码状态格式异常。")

        code = result.get("code")
        if code in (1, "1"):
            return QRCodeCometResult(QRCodeLoginStatus.EXPIRED, "二维码已过期，请刷新。")
        if code not in (0, "0"):
            message = str(result.get("message") or "二维码状态异常，请刷新。")
            return QRCodeCometResult(QRCodeLoginStatus.ERROR, message)

        data = result.get("data")
        if not isinstance(data, dict):
            return QRCodeCometResult(QRCodeLoginStatus.ERROR, "二维码状态缺少数据。")

        state_key = str(data.get("stateKey") or "")
        qr_code = data.get("qrCode")
        if not isinstance(qr_code, dict):
            return QRCodeCometResult(QRCodeLoginStatus.ERROR, "二维码状态缺少扫码信息。")

        status = str(qr_code.get("status") or "")
        if status == "1":
            return QRCodeCometResult(QRCodeLoginStatus.WAITING, "请使用移动交通大学 App 扫码登录。")
        if status == "2":
            return QRCodeCometResult(QRCodeLoginStatus.SCANNED, "已扫码，请在手机上确认登录。")
        if status == "3":
            user_id = str(qr_code.get("userId") or "")
            if not user_id or not state_key:
                return QRCodeCometResult(QRCodeLoginStatus.ERROR, "服务器错误：扫码确认结果缺少登录凭据。")
            return QRCodeCometResult(QRCodeLoginStatus.AUTHORIZED, "扫码确认成功，正在登录。", user_id, state_key)
        if status == "4":
            return QRCodeCometResult(QRCodeLoginStatus.CANCELLED, "已在手机上取消登录，请刷新二维码。")
        return QRCodeCometResult(QRCodeLoginStatus.ERROR, "未知二维码状态，请刷新。")

    def login_qrcode(
            self,
            user_id: str | None = None,
            state_key: str | None = None,
            account_type: NewLogin.AccountType = NewLogin.POSTGRADUATE,
            trust_agent: bool = True) -> tuple[LoginState, Union[NewLogin.MFAContext, object, None]]:
        """
        使用扫码授权后得到的 userId 和 stateKey 提交统一认证登录。
        """
        if self._already_authenticated_response is not None:
            authenticated_response = self._already_authenticated_response
            self._already_authenticated_response = None
            self.has_login = True
            self.postLogin(authenticated_response)
            return LoginState.SUCCESS, self.session

        if self._choose_account_response:
            return self._finish_account_choice(account_type, trust_agent=trust_agent)

        if self._safety_verify_response is not None:
            if not self._safety_verify_mfa_requested:
                return self._require_safety_verify_mfa(self._safety_verify_response)
            return self._finish_safety_verify()

        if self.has_login:
            raise RuntimeError("已经登录，不能重复登录。请重新创建 NewQRCodeLogin 对象以登录其他账号。")

        if user_id is not None and state_key is not None:
            self._qr_user_id = user_id
            self._qr_state_key = state_key
        elif self._qr_user_id is None or self._qr_state_key is None:
            raise ValueError("首次调用 login_qrcode 时必须提供 user_id 和 state_key。")

        if self.execution_input is None:
            raise ServerError(500, "服务器返回的登录页缺少 execution 字段。")

        if self.mfa_enabled and self.mfa_qrcode_login_enabled and (
                self.mfa_context is None or not self.mfa_context.required):
            response = self._post(
                "https://login.xjtu.edu.cn/cas/mfa/detect",
                data={
                    "username": self._qr_user_id,
                    "password": self._qr_state_key,
                    "fpVisitorId": self.fp_visitor_id,
                    "loginType": "qrCodeLogin",
                },
                headers={"Referer": self.post_url},
            )
            try:
                data = response.json()
            except ValueError as exc:
                raise ServerError(500, "服务器在二维码 MFA 验证时返回了无法解析的信息") from exc
            if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
                raise ServerError(500, "服务器在二维码 MFA 验证时返回了无法识别的信息")

            result_data = data["data"]
            state = str(result_data.get("state") or "")
            need = result_data.get("need") is True
            self.mfa_context = self.MFAContext(
                self,
                state,
                required=need,
                flow=self.MFAFlow.MFA_DETECT,
            )
            if need:
                return LoginState.REQUIRE_MFA, self.mfa_context

        mfa_state = self.mfa_context.state if self.mfa_context else ""
        if self.mfa_context is not None and self.mfa_context.required:
            current_trust_agent = "true" if trust_agent else "false"
        else:
            current_trust_agent = ""

        login_response = self._post(
            self.post_url,
            data={
                "username": self._qr_user_id,
                "password": self._qr_state_key,
                "currentMenu": "3",
                "mfaState": mfa_state,
                "execution": self.execution_input,
                "_eventId": "submitQrCodeKey",
                "geolocation": "",
                "fpVisitorId": self.fp_visitor_id,
                "trustAgent": current_trust_agent,
            },
            allow_redirects=True,
        )
        return self._process_login_response(login_response)


class NewQRCodeLogin(QRCodeLoginMixin, NewLogin):
    """
    通过统一认证二维码扫码完成登录。
    """

    def __init__(self, login_url: str, session: requests.Session | None = None,
                 visitor_id: str | None = None) -> None:
        """
        创建二维码登录器。
        """
        super().__init__(login_url, session=session, visitor_id=visitor_id)


class NewWebVPNQRCodeLogin(QRCodeLoginMixin, NewWebVPNLogin):
    """
    通过 WebVPN 改写统一认证请求的二维码登录器。
    """

    def __init__(self, login_url: str, session: requests.Session | None = None,
                 visitor_id: str | None = None) -> None:
        """
        创建 WebVPN 二维码登录器。
        """
        super().__init__(login_url, session=session, visitor_id=visitor_id)


NewQRCodeWebVPNLogin = NewWebVPNQRCodeLogin
