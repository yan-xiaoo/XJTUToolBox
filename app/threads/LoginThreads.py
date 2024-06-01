from enum import Enum

from auth import Login, EHALL_LOGIN_URL, ServerError
from PyQt5.QtCore import QThread, pyqtSignal


class LoginChoice(Enum):
    GET_SHOW_CAPTCHA = 0,
    GET_CAPTCHA_CODE = 1,
    LOGIN = 2,
    GET_STUDENT_ID = 3


class LoginThread(QThread):
    """登录线程，负责在子线程中完成登录所需的网络请求，通过发送信号返回请求结果。"""
    # 是否需要显示验证码。此信号应当连接到具有一个参数槽函数。参数为 True: 需要验证码, False: 不需要验证码
    isShowCaptcha = pyqtSignal(bool)
    captchaCode = pyqtSignal(bytes)
    # 获得学号后，传输学号的信号
    studentID = pyqtSignal(str)
    # 信号：登录失败。第一个参数表示是否可继续（可继续：服务器有响应，只是回答密码错误之类的。不可继续：断网等情况），第二个参数表示具体错误。
    loginFailed = pyqtSignal(bool, str)
    loginSuccess = pyqtSignal()

    LoginChoice = LoginChoice

    def __init__(self, choice: LoginChoice, username: str, password: str, captcha=None, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.username = username
        self.password = password
        self.captcha = captcha
        # 稍后初始化，避免立刻产生网络请求
        self.login = None

    def run(self):
        try:
            self.login = self.login or Login(EHALL_LOGIN_URL)
            if self.choice == LoginChoice.GET_SHOW_CAPTCHA:
                result = self.login.isShowJCaptchaCode(self.username)
                self.isShowCaptcha.emit(result)

            elif self.choice == LoginChoice.GET_CAPTCHA_CODE:
                code = self.login.getJCaptchaCode()
                self.captchaCode.emit(code)

            elif self.choice == LoginChoice.LOGIN:
                try:
                    self.login.login(self.username, self.password, self.captcha or "")
                except ServerError as e:
                    self.loginFailed.emit(True, e.message)
                else:
                    self.loginSuccess.emit()
            elif self.choice == LoginChoice.GET_STUDENT_ID:
                try:
                    self.login.getUserIdentity()
                except ServerError as e:
                    self.loginFailed.emit(True, e.message)
                else:
                    self.studentID.emit(self.login.personNo)
            else:
                raise ValueError("Invalid choice")
        except ServerError as e:
            self.loginFailed.emit(True, e.message)
        except Exception as e:
            self.loginFailed.emit(False, str(e))
