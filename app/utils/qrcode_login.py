from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.utils.mfa import MFACancelledError, MFAUnavailableError
from auth.new_qrcode_login import QRCodeLoginMixin


class QRCodeLoginActionType(Enum):
    """
    二维码登录对话框向业务线程返回的用户动作类型。
    """
    REFRESH = "refresh"
    CANCEL = "cancel"


@dataclass(frozen=True)
class QRCodeLoginAction:
    """
    用户在二维码登录对话框中触发的一次动作。
    """
    type: QRCodeLoginActionType


@dataclass(frozen=True)
class QRCodeLoginRequest:
    """
    一次二维码登录请求的展示上下文。
    """
    account_uuid: str
    account_name: str
    site_key: str
    site_name: str


@dataclass(frozen=True)
class QRCodeLoginResult:
    """
    二维码扫码确认后得到的统一认证临时登录凭据。
    """
    user_id: str
    state_key: str


class QRCodeLoginError(Exception):
    """
    二维码登录交互过程中发生的应用层错误。
    """


class QRCodeLoginCancelledError(QRCodeLoginError, MFACancelledError):
    """
    用户在桌面端取消二维码扫码登录。
    """


class QRCodeLoginUnavailableError(QRCodeLoginError, MFAUnavailableError):
    """
    当前环境没有可用的二维码登录交互提供者。
    """


class QRCodeLoginProvider(Protocol):
    """
    应用层二维码登录交互提供者接口。
    """

    def handle(self, login_util: QRCodeLoginMixin, request: QRCodeLoginRequest) -> QRCodeLoginResult:
        """
        处理一次二维码扫码登录交互。
        """

    def submit_action(self, action: QRCodeLoginAction) -> None:
        """
        接收主线程 UI 提交的二维码登录用户动作。
        """
