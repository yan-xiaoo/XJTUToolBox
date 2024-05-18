from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QVBoxLayout, QWidget, QFrame, QHBoxLayout, QDialog
from qfluentwidgets import TitleLabel, ScrollArea, LineEdit, PasswordLineEdit, PrimaryPushButton, PushButton, \
    ImageLabel, InfoBar, InfoBarPosition, StateToolTip, isDarkTheme, Theme

from ..threads.LoginThreads import LoginThread
from ..utils import StyleSheet, cfg


class LoginInterface(ScrollArea):
    """登录界面"""
    # 此元件发出的信号
    loginSuccess = pyqtSignal(str, str)
    loginFail = pyqtSignal()
    cancel = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("LoginInterface")
        self.view = QWidget(self)
        self.view.setObjectName("scrollWidget")

        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignHCenter)

        self.setWidget(self.view)
        self.setWidgetResizable(True)

        # 界面标题
        self.titleLabel = TitleLabel(self.tr("登录"), self.view)
        self.vBoxLayout.addWidget(self.titleLabel, alignment=Qt.AlignHCenter)

        # 用户名-密码输入区域
        self.namePwdFrame = QFrame(self.view)
        self.namePwdFrame.setObjectName("NamePwdFrame")
        self.vBoxLayout.addWidget(self.namePwdFrame)
        self.namePwdFrame.setContentsMargins(0, 0, 0, 30)
        vBoxLayout = QVBoxLayout(self.namePwdFrame)
        vBoxLayout.setAlignment(Qt.AlignHCenter)
        # 用户名输入框
        self.userNameEdit = LineEdit(self.namePwdFrame)
        self.userNameEdit.setPlaceholderText(self.tr("学号/手机号/邮箱"))
        vBoxLayout.addWidget(self.userNameEdit)

        # 密码输入框
        self.passwordEdit = PasswordLineEdit(self.namePwdFrame)
        self.passwordEdit.setPlaceholderText(self.tr("密码"))
        vBoxLayout.addWidget(self.passwordEdit)

        # 验证码输入区域
        self.captchaFrame = QFrame(self.view)
        self.captchaFrame.setObjectName("CaptchaFrame")
        self.vBoxLayout.addWidget(self.captchaFrame)
        hBoxLayout = QHBoxLayout(self.captchaFrame)
        hBoxLayout.setAlignment(Qt.AlignHCenter)
        self.captchaEdit = LineEdit(self.captchaFrame)
        self.captchaEdit.setPlaceholderText(self.tr("验证码"))
        hBoxLayout.addWidget(self.captchaEdit)
        self.captchaLabel = ImageLabel(self.captchaFrame)
        hBoxLayout.addWidget(self.captchaLabel)
        # 默认情况下隐藏验证码输入区域
        self.captchaFrame.setVisible(False)

        # 登录与取消按钮
        self.loginButton = PrimaryPushButton(self.tr("登录"), self)
        self.vBoxLayout.addWidget(self.loginButton)
        self.cancelButton = PushButton(self.tr("取消"), self)
        self.vBoxLayout.addWidget(self.cancelButton)

        # 登录进度提示
        self.stateToolTip = None

        # 应用 qss
        StyleSheet.LOGIN_INTERFACE.apply(self)

        # 控制逻辑用的变量
        self._captcha_required = False
        self.__thread = LoginThread(LoginThread.LoginChoice.GET_SHOW_CAPTCHA, "", "", parent=self)
        # 在用户点击登录按钮时立刻保存变量，防止登录到一半结果输入框里东西被用户改了（
        self.__username = ""
        self.__password = ""
        self.__captcha = ""

        # 连接信号-槽
        self.loginButton.clicked.connect(self.on_loginButton_clicked)
        self.cancelButton.clicked.connect(self.on_cancelButton_clicked)
        self.captchaLabel.clicked.connect(self.on_refresh_captcha_clicked)
        self.loginSuccess.connect(self.on_login_success)

        self.__thread.loginSuccess.connect(self.__on_login_success)
        self.__thread.loginFailed.connect(self.__on_login_fail)
        self.__thread.captchaCode.connect(self.__on_receive_captcha_code)

    def _show_captcha(self, refresh=True):
        """显示验证码输入区域，同时标记验证码为必须填写的区域。"""
        self.captchaFrame.setVisible(True)
        if refresh:
            self.on_refresh_captcha_clicked()
        self._captcha_required = True

    def _hide_captcha(self):
        """隐藏验证码输入区域，同时标记验证码为非必须填写的区域。"""
        self.captchaFrame.setVisible(False)
        self.captchaEdit.clear()
        self._captcha_required = False

    def _lock(self):
        """锁定登录按钮，以防止用户重复点击。"""
        self.loginButton.setDisabled(True)
        self.stateToolTip = StateToolTip("登录中", "请稍等...", self)
        self.stateToolTip.move(self.stateToolTip.getSuitablePos())
        self.stateToolTip.show()

    def _unlock(self, success=False):
        """
        解锁登录按钮。
        :param success: 登录是否成功
        """
        self.loginButton.setDisabled(False)
        if success:
            self.stateToolTip.setContent("登录成功")
            self.stateToolTip.setState(True)
        else:
            self.stateToolTip.hide()

    @pyqtSlot()
    def on_loginButton_clicked(self):
        """处理用户点击登录按钮后的事件"""
        if self.userNameEdit.text() == "" or self.passwordEdit.text() == "":
            InfoBar.warning(title="用户名或密码未填写", content="", orient=Qt.Horizontal, isClosable=False,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            return
        if self.captchaEdit.text() == "" and self._captcha_required:
            InfoBar.warning(title="验证码未填写", content="", orient=Qt.Horizontal, isClosable=False,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            return
        # 开始登录
        # 添加登录冷却，在一次登录没有完成前，不能再次点击登录按钮。
        self._lock()
        self.__username = self.userNameEdit.text()
        self.__password = self.passwordEdit.text()
        self.__captcha = self.captchaEdit.text()

        # 登录流程：
        # 1. 检查是否需要验证码（已经需要则跳过此判断）
        # 2. 如果需要验证码且之前不需要，则获取验证码并中断登录
        # 3. 登录（__on_isShowCaptcha_finished 函数中）
        # 4. 登录成功处理（发送信号，__on_login_success 函数中）
        # 5. 登录失败处理：发送信号，检查是否需要验证码（__on_login_fail 与 __on_double_check_isShowCaptcha 函数中）
        # 其中所有网络通信部分全部在 QThread 中完成以防止主线程阻塞；逻辑部分分布于其他函数中，通过信号-槽机制与 QThread 中的信号连接而被调用
        if self._captcha_required:
            self.__on_isShowCaptcha_finished(True)
        else:
            self.__thread.username = self.__username
            self.__thread.choice = LoginThread.LoginChoice.GET_SHOW_CAPTCHA
            self.__thread.isShowCaptcha.connect(self.__on_isShowCaptcha_finished)
            self.__thread.start()

    @pyqtSlot()
    def on_cancelButton_clicked(self):
        """处理用户点击取消按钮后的事件"""
        self.cancel.emit()

    @pyqtSlot()
    def on_refresh_captcha_clicked(self):
        """处理用户点击验证码标签刷新验证码后的事件"""
        if not self.userNameEdit.text():
            return
        self.__thread.username = self.userNameEdit.text()
        self.__thread.choice = LoginThread.LoginChoice.GET_CAPTCHA_CODE
        self.__thread.start()

    @pyqtSlot(bytes)
    def __on_receive_captcha_code(self, code: bytes):
        """处理获取验证码的信号"""
        self.captchaLabel.setPixmap(QPixmap.fromImage(QImage.fromData(code)))
        self.captchaLabel.setScaledContents(True)
        self.captchaLabel.setFixedSize(100, 30)
        self.captchaLabel.setToolTip("点击刷新验证码")

    @pyqtSlot()
    def __on_login_success(self):
        self.loginSuccess.emit(self.__username, self.__password)
        self._unlock(True)

    @pyqtSlot(bool)
    def __on_double_check_isShowCaptcha(self, show: bool):
        self.__thread.isShowCaptcha.disconnect(self.__on_double_check_isShowCaptcha)
        if show:
            self._show_captcha(refresh=True)
        else:
            self._hide_captcha()
        self._unlock(False)

    @pyqtSlot(str)
    def __on_login_fail(self, msg: str):
        InfoBar.error("登录失败", msg,
                      orient=Qt.Horizontal, isClosable=False,
                      position=InfoBarPosition.TOP_RIGHT, duration=3000,
                      parent=self)
        self.__thread.username = self.__username
        self.__thread.choice = LoginThread.LoginChoice.GET_SHOW_CAPTCHA
        self.__thread.isShowCaptcha.connect(self.__on_double_check_isShowCaptcha)
        self.__thread.start()

    @pyqtSlot(bool)
    def __on_isShowCaptcha_finished(self, show: bool):
        try:
            self.__thread.isShowCaptcha.disconnect(self.__on_isShowCaptcha_finished)
        except TypeError:
            pass
        # 处理「本次登录需要验证码了但是用户没填」的情况
        if show and not self._captcha_required:
            self._show_captcha(refresh=True)
            InfoBar.info("请输入验证码", "", orient=Qt.Horizontal, isClosable=True,
                         position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            self._unlock(False)
            return
        if not show:
            self._hide_captcha()
        # 登录
        self.__thread.username = self.__username
        self.__thread.password = self.__password
        self.__thread.choice = LoginThread.LoginChoice.LOGIN
        if self._captcha_required:
            self.__thread.captcha = self.__captcha
        self.__thread.start()

    @pyqtSlot(str, str)
    def on_login_success(self, username: str, password: str):
        pass


class LoginDialog(QDialog):
    """将登录面板封装为一个弹出式对话框"""
    # 登录成功时，发送此信号
    loginSuccess = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        c = 0 if isDarkTheme() else 255
        self.setStyleSheet(f'background:rgba({c}, {c}, {c}, 0.6)')

        self.login_interface = LoginInterface(self)
        self.login_interface.setFixedSize(500, 400)
        self.viewLayout = QVBoxLayout(self)
        self.viewLayout.addWidget(self.login_interface)

        self.login_interface.cancel.connect(self._on_cancelButton_clicked)
        self.login_interface.loginSuccess.connect(self._on_loginSuccess)

        self.window().installEventFilter(self)

    def _on_cancelButton_clicked(self):
        self.reject()
        self.rejected.emit()

    @pyqtSlot(str, str)
    def _on_loginSuccess(self, username, password):
        self.accept()
        self.accepted.emit()
        self.loginSuccess.emit(username, password)
