from __future__ import annotations

from enum import Enum

from requests import HTTPError

from app.utils import logger, cfg
from auth import ServerError
from PyQt5.QtCore import QThread, pyqtSignal

from auth.new_login import NewLogin, LoginState
from app.utils.mfa import MFACancelledError, MFAProvider, MFARequest, MFAUnavailableError
from ywtb import YWTBLogin
from ywtb.util import YWTBUtil


class LoginChoice(Enum):
    GET_SHOW_CAPTCHA = 0,
    GET_CAPTCHA_CODE = 1,
    LOGIN = 2,
    GET_STUDENT_ID = 3
    FINISH_LOGIN = 4


class LoginThread(QThread):
    """登录线程，负责在子线程中完成登录所需的网络请求，通过发送信号返回请求结果。"""
    # 是否需要显示验证码。此信号应当连接到具有一个参数槽函数。参数为 True: 需要验证码, False: 不需要验证码
    isShowCaptcha = pyqtSignal(bool)
    captchaCode = pyqtSignal(bytes)
    # 获得学号和账户类型后，传输信息的信号
    # 传输学号、账号类型、姓名
    studentInfo = pyqtSignal(str, object, str)
    # 信号：登录失败。第一个参数表示是否可继续（可继续：服务器有响应，只是回答密码错误之类的。不可继续：断网等情况），第二个参数表示具体错误。
    loginFailed = pyqtSignal(bool, str)
    # 登录成功信号
    loginSuccess = pyqtSignal()
    # 需要选择账户信号
    needChooseAccount = pyqtSignal()
    LoginChoice = LoginChoice

    def __init__(
            self,
            choice: LoginChoice,
            username: str,
            password: str,
            captcha: str | None = None,
            mfa_provider: MFAProvider | None = None,
            parent=None):
        super().__init__(parent)
        self.choice = choice
        self.username = username
        self.password = password
        self.captcha = captcha
        # 稍后初始化，避免立刻产生网络请求
        self.login = None
        # 选择的账户类型
        self.accountType = None
        # MFA 交互提供者
        self.mfa_provider = mfa_provider
        # 是否信任当前客户端
        self.trustAgent = True

    def run(self):
        try:
            self.login = self.login or YWTBLogin(visitor_id=str(cfg.loginId.value))
            if self.choice == LoginChoice.GET_SHOW_CAPTCHA:
                result = self.login.isShowJCaptchaCode()
                self.isShowCaptcha.emit(result)

            elif self.choice == LoginChoice.GET_CAPTCHA_CODE:
                code = self.login.getJCaptchaCode()
                self.captchaCode.emit(code)

            elif self.choice == LoginChoice.LOGIN:
                try:
                    # 检查账户是否存在多个身份
                    status, info = self.login.login(self.username, self.password, self.captcha or "", trust_agent=self.trustAgent)
                    self._handle_login_status(status, info)
                except (MFACancelledError, MFAUnavailableError) as e:
                    logger.info("MFA 验证未完成：%s", e)
                    self.loginFailed.emit(False, str(e))
                except ServerError as e:
                    logger.error("服务器错误", exc_info=True)
                    self.loginFailed.emit(True, e.message)

            elif self.choice == LoginChoice.FINISH_LOGIN:
                try:
                    if self.accountType is None:
                        raise ValueError("必须选择账户类型")
                    status, info = self.login.login(account_type=self.accountType, trust_agent=self.trustAgent)
                    self._handle_login_status(status, info)
                except (MFACancelledError, MFAUnavailableError) as e:
                    logger.info("MFA 验证未完成：%s", e)
                    self.loginFailed.emit(False, str(e))
                except ServerError as e:
                    logger.error("服务器错误", exc_info=True)
                    self.loginFailed.emit(False, e.message)
            elif self.choice == LoginChoice.GET_STUDENT_ID:
                try:
                    ywtb_util = YWTBUtil(self.login.session)
                    result = ywtb_util.getUserInfo()
                except HTTPError as e:
                    logger.error("网络错误", exc_info=True)
                    self.loginFailed.emit(False, str(e))
                except Exception as e:
                    logger.error("其他错误", exc_info=True)
                    self.loginFailed.emit(False, str(e))
                else:
                    if result["attributes"]["identityTypeCode"] == "S01":
                        account_type = NewLogin.AccountType.UNDERGRADUATE
                    elif result["attributes"]["identityTypeCode"] == "S02":
                        account_type = NewLogin.AccountType.POSTGRADUATE
                    else:
                        raise ServerError(-1, "服务器返回了未知的身份类型代码：" + result["attributes"]["identityTypeCode"])
                    self.studentInfo.emit(result["username"], account_type, result["attributes"]["userName"])
            else:
                raise ValueError("Invalid choice")
        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            self.loginFailed.emit(True, e.message)
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.loginFailed.emit(False, str(e))

    def _handle_login_status(self, status: LoginState, info: NewLogin.MFAContext | object | None) -> None:
        """
        处理 NewLogin 状态机返回的登录状态。
        """
        while True:
            if status == LoginState.SUCCESS:
                self.loginSuccess.emit()
                return

            if status == LoginState.REQUIRE_ACCOUNT_CHOICE:
                self.needChooseAccount.emit()
                return

            if status == LoginState.REQUIRE_MFA:
                if not isinstance(info, NewLogin.MFAContext):
                    raise ServerError(500, "服务器返回了无法识别的 MFA 上下文。")
                if self.mfa_provider is None:
                    raise MFAUnavailableError("登录需要 MFA 验证，但当前没有可用的 MFA 交互提供者。")
                phone_number = info.get_phone_number()
                request = MFARequest(
                    # 登录时还没有账户 UUID，所以先用一个固定值占位，等 MFA 验证完成后再更新为实际的账户 UUID
                    account_uuid="login-draft",
                    # 登录时同样还没有账户名称；采用用户输入的用户名占位。
                    account_name=self.username,
                    site_key="account-login",
                    site_name="统一身份认证",
                    phone_number=phone_number,
                )
                self.trustAgent = self.mfa_provider.handle(info, request)
                status, info = self.login.login(trust_agent=self.trustAgent)
                continue

            if status == LoginState.FAIL:
                logger.error("登录错误: \n%s", info)
                self.loginFailed.emit(True, str(info))
                return

            raise ValueError("未知的登录状态")
