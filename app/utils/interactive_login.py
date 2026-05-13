from __future__ import annotations

from auth import ServerError
from auth.new_login import LoginState, NewLogin
from auth.new_qrcode_login import QRCodeLoginMixin

from app.utils.account import Account
from app.utils.mfa import MFAProvider, MFARequest, MFAUnavailableError
from app.utils.qrcode_login import QRCodeLoginProvider, QRCodeLoginRequest, QRCodeLoginUnavailableError


def login_with_optional_mfa(
        login_util: NewLogin,
        username: str,
        password: str,
        account: Account | None,
        mfa_provider: MFAProvider | None,
        account_type: NewLogin.AccountType = NewLogin.POSTGRADUATE,
        site_key: str = "",
        site_name: str = "",
        jcaptcha: str = "",
        trust_agent: bool = True) -> None:
    """
    执行统一认证登录，并在需要 MFA 时通过应用层 provider 原地完成验证。

    该函数对于各种登录情况的处理逻辑如下：
    LoginState.SUCCESS: 直接返回，登录成功。
    LoginState.FAIL: 抛出 ServerError，message 包含登录失败的原因。
    LoginState.REQUIRE_CAPTCHA: 抛出 ServerError，message 提示需要验证码，不处理
    LoginState.REQUIRE_ACCOUNT_CHOICE: 重新调用 login_util.login() 让用户选择账户后继续登录流程。
    LoginState.REQUIRE_MFA: 通过给出的 mfa_provider 完成两步验证流程，完成后继续登录流程。

    简单来讲，就是只处理“服务端要求两步验证”这一种异常情况，不处理其他任何异常情况。
    """
    current_trust_agent = trust_agent
    status, info = login_util.login(
        username,
        password,
        jcaptcha,
        account_type=account_type,
        trust_agent=current_trust_agent,
    )

    while True:
        if status == LoginState.SUCCESS:
            return

        if status == LoginState.FAIL:
            raise ServerError(100, f"登录失败: {info}")

        if status == LoginState.REQUIRE_CAPTCHA:
            raise ServerError(101, "登录需要验证码。")

        if status == LoginState.REQUIRE_ACCOUNT_CHOICE:
            status, info = login_util.login(account_type=account_type, trust_agent=current_trust_agent)
            continue

        if status == LoginState.REQUIRE_MFA:
            if not isinstance(info, NewLogin.MFAContext):
                raise ServerError(500, "服务器返回了无法识别的 MFA 上下文。")
            if mfa_provider is None:
                raise MFAUnavailableError("登录需要 MFA 验证，但当前没有可用的 MFA 交互提供者。")

            phone_number = info.get_phone_number()
            request = _build_mfa_request(account, username, site_key, site_name, phone_number)
            current_trust_agent = mfa_provider.handle(info, request)
            status, info = login_util.login(trust_agent=current_trust_agent)
            continue

        raise ServerError(500, "未知的登录状态。")


def login_with_qrcode(
        login_util: QRCodeLoginMixin,
        account: Account | None,
        qrcode_provider: QRCodeLoginProvider | None,
        mfa_provider: MFAProvider | None,
        account_type: NewLogin.AccountType = NewLogin.POSTGRADUATE,
        site_key: str = "",
        site_name: str = "",
        trust_agent: bool = True) -> None:
    """
    执行统一认证二维码登录，并复用现有 MFA 流程处理后续安全验证。
    """
    current_trust_agent = trust_agent
    request = _build_qrcode_request(account, site_key, site_name)
    if _can_continue_qrcode_login_without_scan(login_util):
        status, info = login_util.login_qrcode(
            account_type=account_type,
            trust_agent=current_trust_agent,
        )
    else:
        if qrcode_provider is None:
            raise QRCodeLoginUnavailableError("登录需要扫码确认，但当前没有可用的二维码登录交互提供者。")
        result = qrcode_provider.handle(login_util, request)
        status, info = login_util.login_qrcode(
            result.user_id,
            result.state_key,
            account_type=account_type,
            trust_agent=current_trust_agent,
        )

    while True:
        if status == LoginState.SUCCESS:
            return

        if status == LoginState.FAIL:
            raise ServerError(100, f"登录失败: {info}")

        if status == LoginState.REQUIRE_CAPTCHA:
            raise ServerError(101, "二维码登录不应要求验证码，请刷新二维码后重试。")

        if status == LoginState.REQUIRE_ACCOUNT_CHOICE:
            status, info = login_util.login_qrcode(account_type=account_type, trust_agent=current_trust_agent)
            continue

        if status == LoginState.REQUIRE_MFA:
            if not isinstance(info, NewLogin.MFAContext):
                raise ServerError(500, "服务器返回了无法识别的 MFA 上下文。")
            if mfa_provider is None:
                raise MFAUnavailableError("登录需要 MFA 验证，但当前没有可用的 MFA 交互提供者。")

            phone_number = info.get_phone_number()
            mfa_request = _build_mfa_request(account, request.account_name, site_key, site_name, phone_number)
            current_trust_agent = mfa_provider.handle(info, mfa_request)
            status, info = login_util.login_qrcode(account_type=account_type, trust_agent=current_trust_agent)
            continue

        raise ServerError(500, "未知的登录状态。")


def _can_continue_qrcode_login_without_scan(login_util: QRCodeLoginMixin) -> bool:
    """
    判断登录器是否已经处在无需首次扫码凭据即可继续推进的状态。
    """
    return (
        getattr(login_util, "_already_authenticated_response", None) is not None
        or getattr(login_util, "_choose_account_response", None) is not None
        or getattr(login_util, "_safety_verify_response", None) is not None
    )


def _build_mfa_request(
        account: Account | None,
        fallback_account_name: str,
        site_key: str,
        site_name: str,
        phone_number: str) -> MFARequest:
    """
    根据账户与站点信息构造应用层 MFA 请求上下文。
    """
    # 默认情况下，如果没有账户信息，就用一些固定值占位，等 MFA 验证完成后再更新为实际的账户 UUID 和账户名称
    if account is None:
        account_uuid = "login-draft"
        account_name = fallback_account_name
    else:
        account_uuid = account.uuid
        account_name = account.nickname or account.username

    return MFARequest(
        account_uuid=account_uuid,
        account_name=account_name,
        site_key=site_key,
        site_name=site_name or site_key or "统一身份认证",
        phone_number=phone_number,
    )


def _build_qrcode_request(
        account: Account | None,
        site_key: str,
        site_name: str) -> QRCodeLoginRequest:
    """
    根据账户与站点信息构造应用层二维码登录请求上下文。
    """
    if account is None:
        account_uuid = "login-draft"
        account_name = "当前账户"
    else:
        account_uuid = account.uuid
        account_name = account.nickname or account.username

    return QRCodeLoginRequest(
        account_uuid=account_uuid,
        account_name=account_name,
        site_key=site_key,
        site_name=site_name or site_key or "统一身份认证",
    )
