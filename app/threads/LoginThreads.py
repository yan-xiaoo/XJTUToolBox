import json.decoder
from enum import Enum

from requests import HTTPError

from app.utils import logger, cfg
from auth import ServerError
from PyQt5.QtCore import QThread, pyqtSignal

from auth.new_login import NewLogin, LoginState
from ywtb import YWTBLogin
from ywtb.util import YWTBUtil


class LoginChoice(Enum):
    GET_SHOW_CAPTCHA = 0,
    GET_CAPTCHA_CODE = 1,
    LOGIN = 2,
    GET_STUDENT_ID = 3
    FINISH_LOGIN = 4
    MFA_SEND = 5
    MFA_VERIFY = 6


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
    # 需要 MFA 信号（数据：手机号）
    needMFA = pyqtSignal(str)
    # 发送验证码结果
    sendMFAResult = pyqtSignal(bool, str)

    LoginChoice = LoginChoice

    def __init__(self, choice: LoginChoice, username: str, password: str, captcha=None, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.username = username
        self.password = password
        self.captcha = captcha
        # 稍后初始化，避免立刻产生网络请求
        self.login = None
        # 选择的账户类型
        self.accountType = None
        # MFA Content
        self._mfaContent = None
        # MFA 验证码
        self._mfaCode = None
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
                except ServerError as e:
                    logger.error("服务器错误", exc_info=True)
                    self.loginFailed.emit(True, e.message)
                else:
                    if status == LoginState.SUCCESS:
                        self.loginSuccess.emit()
                    elif status == LoginState.REQUIRE_ACCOUNT_CHOICE:
                        self.needChooseAccount.emit()
                    elif status == LoginState.REQUIRE_MFA:
                        self._mfaContent: NewLogin.MFAContext = info
                        number = self._mfaContent.get_phone_number()
                        self.needMFA.emit(number)
                    elif status == LoginState.FAIL:
                        logger.error("登录错误: \n%s", info)
                        self.loginFailed.emit(True, info)
                    else:
                        raise ValueError("未知的登录状态")
            elif self.choice == LoginChoice.MFA_VERIFY:
                try:
                    if self._mfaContent is None:
                        raise ValueError("MFA 内容未设置")
                    if self._mfaCode is None:
                        raise ValueError("MFA 验证码未设置")
                    self._mfaContent.verify_phone_code(self._mfaCode)
                    status, info = self.login.login(trust_agent=self.trustAgent)
                except ServerError as e:
                    logger.error("服务器错误", exc_info=True)
                    self.loginFailed.emit(True, e.message)
                else:
                    if status == LoginState.SUCCESS:
                        self.loginSuccess.emit()
                    elif status == LoginState.REQUIRE_ACCOUNT_CHOICE:
                        self.needChooseAccount.emit()
                    elif status == LoginState.FAIL:
                        logger.error("登录错误: \n%s", info)
                        self.loginFailed.emit(True, info)
                    else:
                        raise ValueError("未知的登录状态")

            elif self.choice == LoginChoice.MFA_SEND:
                try:
                    if self._mfaContent is None:
                        raise ValueError("MFA 内容未设置")
                    self._mfaContent.send_verify_code()
                except (ServerError, HTTPError, json.decoder.JSONDecodeError) as e:
                    logger.error("发送验证码时发生错误", exc_info=True)
                    self.sendMFAResult.emit(False, str(e))
                else:
                    self.sendMFAResult.emit(True, "")

            elif self.choice == LoginChoice.FINISH_LOGIN:
                try:
                    if self.accountType is None:
                        raise ValueError("必须选择账户类型")
                    self.login.login(account_type=self.accountType, trust_agent=self.trustAgent)
                except ServerError as e:
                    logger.error("服务器错误", exc_info=True)
                    self.loginFailed.emit(False, e.message)
                else:
                    self.loginSuccess.emit()
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
