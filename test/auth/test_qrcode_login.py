from __future__ import annotations

import unittest
from typing import cast

from app.utils.interactive_login import login_with_qrcode
from auth.new_login import LoginState
from auth.new_qrcode_login import NewQRCodeLogin, QRCodeLoginStatus


class FakeResponse:
    """
    用于测试二维码轮询解析逻辑的简易响应对象。
    """

    def __init__(self, payload: object) -> None:
        """
        保存将由 json 方法返回的数据。
        """
        self.payload = payload

    def raise_for_status(self) -> None:
        """
        模拟 requests.Response.raise_for_status。
        """

    def json(self) -> object:
        """
        返回预设的 JSON 数据。
        """
        return self.payload


class FakeQRCodeLogin(NewQRCodeLogin):
    """
    不发起网络请求的二维码登录器测试替身。
    """

    def __init__(self, payload: object) -> None:
        """
        保存待解析的二维码轮询响应。
        """
        self.payload = payload
        self.post_url = "https://login.xjtu.edu.cn/cas/login"

    def _post(self, url: str, **kwargs: object) -> FakeResponse:
        """
        返回预设响应而不是发起真实请求。
        """
        return FakeResponse(self.payload)


class FakeSubmitQRCodeLogin(NewQRCodeLogin):
    """
    不发起网络请求的二维码登录提交测试替身。
    """

    def __init__(self) -> None:
        """
        初始化一次需要信任设备选项的二维码登录状态。
        """
        self.session = object()
        self.post_url = "https://login.xjtu.edu.cn/cas/login"
        self.execution_input = "execution"
        self.fp_visitor_id = "visitor"
        self._already_authenticated_response = None
        self._choose_account_response = None
        self._safety_verify_response = None
        self._safety_verify_mfa_requested = False
        self.has_login = False
        self.mfa_enabled = False
        self.mfa_qrcode_login_enabled = False
        self.mfa_context = self.MFAContext(
            self,
            "mfa-state",
            required=True,
            flow=self.MFAFlow.MFA_DETECT,
        )
        self.posted_data: dict[str, str] = {}

    def _post(self, url: str, **kwargs: object) -> FakeResponse:
        """
        保存提交表单而不是发起真实请求。
        """
        self.posted_data = cast(dict[str, str], kwargs["data"])
        return FakeResponse({})

    def _process_login_response(self, login_response: FakeResponse) -> tuple[LoginState, object | None]:
        """
        将提交响应视为登录成功。
        """
        return LoginState.SUCCESS, self.session


class FakeAlreadyAuthenticatedQRCodeLogin:
    """
    模拟 NewLogin 初始化时已经发现目标站点登录成功的二维码登录器。
    """

    def __init__(self) -> None:
        self._already_authenticated_response = object()
        self._choose_account_response = None
        self._safety_verify_response = None
        self.calls = 0

    def login_qrcode(self, *args: object, **kwargs: object) -> tuple[LoginState, object | None]:
        self.calls += 1
        self._already_authenticated_response = None
        return LoginState.SUCCESS, object()


class TestQRCodeLogin(unittest.TestCase):
    """
    测试二维码登录协议解析。
    """

    def test_authorized_status_extracts_credentials(self) -> None:
        """
        已授权状态应提取 userId 和 stateKey。
        """
        login = FakeQRCodeLogin({
            "code": 0,
            "data": {
                "stateKey": "state-key",
                "qrCode": {
                    "status": "3",
                    "userId": "user-id",
                },
            },
        })

        result = login.poll_qrcode_status()

        self.assertEqual(result.status, QRCodeLoginStatus.AUTHORIZED)
        self.assertEqual(result.user_id, "user-id")
        self.assertEqual(result.state_key, "state-key")

    def test_expired_status_is_reported(self) -> None:
        """
        code 为 1 时应报告二维码过期。
        """
        login = FakeQRCodeLogin({"code": 1})

        result = login.poll_qrcode_status()

        self.assertEqual(result.status, QRCodeLoginStatus.EXPIRED)

    def test_cancelled_status_is_reported(self) -> None:
        """
        status 为 4 时应报告用户取消。
        """
        login = FakeQRCodeLogin({
            "code": 0,
            "data": {
                "stateKey": "",
                "qrCode": {
                    "status": "4",
                },
            },
        })

        result = login.poll_qrcode_status()

        self.assertEqual(result.status, QRCodeLoginStatus.CANCELLED)

    def test_trust_agent_false_is_submitted_for_required_mfa(self) -> None:
        """
        MFA 已要求信任设备选择时，不信任应提交 false。
        """
        login = FakeSubmitQRCodeLogin()

        login.login_qrcode("user-id", "state-key", trust_agent=False)

        self.assertEqual(login.posted_data["trustAgent"], "false")

    def test_already_authenticated_qrcode_login_does_not_require_provider(self) -> None:
        """
        目标站点已登录时，二维码分支不应再要求可用的扫码 provider。
        """
        login = FakeAlreadyAuthenticatedQRCodeLogin()

        login_with_qrcode(cast(NewQRCodeLogin, login), None, None, None)

        self.assertEqual(login.calls, 1)


if __name__ == "__main__":
    unittest.main()
