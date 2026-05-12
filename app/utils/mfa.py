from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from auth.new_login import NewLogin


class MFAActionType(Enum):
    """
    MFA 对话框向业务线程返回的用户动作类型。
    """
    # 用户要求发送手机验证码
    SEND_CODE = "send_code"
    # 用户要求输入验证码并验证
    VERIFY_CODE = "verify_code"
    # 用户要求取消 MFA 验证
    CANCEL = "cancel"


@dataclass(frozen=True)
class MFARequest:
    """
    一次应用层 MFA 请求的展示上下文。
    """
    # 登录账户的 uuid
    account_uuid: str
    # 登录账户的名称
    account_name: str
    # 登录目标网站的一个标识符。同一网站的不同 MFA 场景可以使用同一个 site_key。
    site_key: str
    # 登录目标网站的名称，用于在 MFA 对话框中提示用户。
    site_name: str
    # 需要验证的电话号码，只用于展示。
    phone_number: str


@dataclass(frozen=True)
class MFAAction:
    """
    用户在 MFA 对话框中触发的一次动作。
    """
    # 用户动作的类型
    type: MFAActionType
    # 当 type 是 VERIFY_CODE 时，用户输入的验证码；其他类型时忽略。
    code: str = ""
    # 当 type 是 VERIFY_CODE 时，用户是否选择信任当前客户端；其他类型时忽略。
    trust_agent: bool = True


class MFACancelledError(Exception):
    """
    用户取消 MFA 验证。
    """


class MFAUnavailableError(Exception):
    """
    当前环境没有可用的 MFA 交互提供者。
    """


class MFAProvider(Protocol):
    """
    应用层 MFA 交互提供者接口。
    """

    def handle(self, context: NewLogin.MFAContext, request: MFARequest) -> bool:
        """
        处理一次 MFA 交互，并返回用户是否选择信任当前客户端。
        """

    def report_send_result(self, request: MFARequest, success: bool, message: str = "") -> None:
        """
        向 UI 报告验证码发送结果。
        """
