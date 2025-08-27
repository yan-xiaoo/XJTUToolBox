# 此文件实现了 2025 年 7 月 17 日后西安交通大学新统一认证系统的登录，即 login.xjtu.edu.cn。
# 服务端部分处理尚不稳定，因此此文件中提供的 API 也不稳定，在后续版本中可能出现函数名更改/参数更改等情况。
# 此文件会尽可能与登录页面前端实现保持一致，不会尝试利用设计漏洞等方式绕过验证码等安全措施。
import base64
import enum
from typing import List
from urllib.parse import urlparse, parse_qs

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import html

from .util import get_session, ServerError, generate_fp_visitor_id, getVPNUrl


# 使用 lxml 解析 HTML 并提取表单中的 execution 值
def extract_execution_value(html_content):
    """从 HTML 内容中提取 name=execution 的 input 元素的 value"""
    tree = html.fromstring(html_content)
    execution_input = tree.xpath('//input[@name="execution"]/@value')
    return execution_input[0] if execution_input else None


def extract_account_choices(html_content):
    """
    从账户选择页面中提取账户选项信息
    Args:
        html_content (str): HTML 内容
    Returns:
        list: 包含账户选项信息的列表，每个元素是字典，包含 'name', 'label' 字段
              如果未找到账户选择页面则返回 None
    """
    tree = html.fromstring(html_content)

    # 查找所有的 account-wrap div
    account_wraps = tree.xpath('//div[@class="account-wrap"]')

    if not account_wraps:
        return None

    account_choices = []

    for wrap in account_wraps:
        # 在每个 account-wrap 中查找 name 和 el-radio 的 label
        name_elem = wrap.xpath('.//div[@class="name"]')
        radio_elem = wrap.xpath('.//el-radio[@class="checkbox-radio"]')

        if name_elem and radio_elem:
            name = name_elem[0].text_content().strip()
            label = radio_elem[0].get('label', '')

            account_choices.append({
                'name': name,
                'label': label
            })

    return account_choices if account_choices else None


def extract_alert_message(html_content):
    """
    提取 el-alert 组件的错误信息
    Args:
        html_content (str): HTML 内容
    Returns:
        dict: 包含 title, type, show_icon 信息的字典，如果未找到则返回 None
    """
    tree = html.fromstring(html_content)
    # 查找 el-alert 元素
    alert_elements = tree.xpath('//el-alert')
    if not alert_elements:
        return None
    # 获取第一个 el-alert 元素的属性
    alert = alert_elements[0]
    result = {
        'title': alert.get('title', ''),
        'type': alert.get('type', ''),
        'show_icon': alert.get('show-icon', '') == 'true' or alert.get('show-icon') == '',
        'text_content': alert.text_content().strip() if alert.text_content() else ''
    }
    return result


class NewLogin:
    """
    通过西安交通大学统一身份认证网站，登录目标网页。
    此类用于 2025 年 7 月 17 日后的统一认证系统，即 login.xjtu.edu.cn。
    登录流程根据是否需要动态选择身份可以分为两种。
    首先需要了解，登录系统在待登录账号具有多种身份（即是本科生又是研究生）并且使用手机号/邮箱而非学号登录时，会出现额外的页面，要求选择登录账号。
    在登录前，我们无法预测待登录的账号是不是这样的需要选择身份的账号。因此，我们提供了两种互斥的登录 API：
    1. 预先指定账号身份：只使用 login 方法登录。
    > from auth import EHALL_LOGIN_URL
    > from auth.new_login import NewLogin
    > # 选择登录网站（比如 Ehall）
    > login = NewLogin(EHALL_LOGIN_URL)
    > # 登录。这里 account_type 用于预先指定需要选择的身份。如果待登录账号没有多个身份，此参数没有作用；如果有多个身份，则按照此参数输入选择身份。
    > session = login.login("username", "password", account_type=NewLogin.POSTGRADUATE)
    > # session 即为登录后的 Session 对象，可以用来访问目标网站
    2. 动态选择身份：采用 checkForBothAccounts + finishLogin 方法登录。
    这种方法可以先获得账号是否有多个身份，如果有，再让用户选择需要登录的身份，最后完成登录。
    这种方法适用于需要用户交互选择身份的场景，比如图形界面程序。
    > from auth import EHALL_LOGIN_URL
    > from auth.new_login import NewLogin
    > # 选择登录网站（比如 Ehall）
    > login = NewLogin(EHALL_LOGIN_URL)
    > # 获取当前账号下是否有两个身份
    > has_both_accounts = login.checkForBothAccounts("username", "password")
    > if has_both_accounts:
    >   type_ = input("请输入需要登录的身份（0: 本科生, 1: 研究生）:")
    >   if type_ == "0":
    >       account_type = NewLogin.UNDERGRADUATE
    >   elif type_ == "1":
    >       account_type = NewLogin.POSTGRADUATE
    >   else:
    >       raise ValueError("未知的身份类型")
    >   # 选择单个身份登录
    >   session = login.finishLogin(account_type)
    两种登录方法只能选择一种，绝对不能混合使用。如果多次登录，登录系统会返回 404 错误。
    """
    class AccountType(enum.Enum):
        UNDERGRADUATE = 0
        POSTGRADUATE = 1

    UNDERGRADUATE = AccountType.UNDERGRADUATE
    POSTGRADUATE = AccountType.POSTGRADUATE

    def __init__(self, login_url: str, session=None):
        """
        通过网址执行登录。
        :param login_url: 一个登录网址。在浏览器中打开此网址后，应当跳转到统一身份认证登录界面，
        且登录成功后可以返回到目标网页。
        :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
        """
        if session is None:
            session = get_session()

        self.session = session
        # 获得提交登录信息的地址
        response = self._get(login_url,
                             allow_redirects=True)
        self.post_url = response.url
        # 获得 execution 字段
        self.execution_input = extract_execution_value(response.text)
        # 获得一个标识符
        self.fp_visitor_id = generate_fp_visitor_id()
        # 目前服务端在本地存储登录失败次数，实现是否填写验证码的判断，我也暂时这么实现
        self.fail_count = 0
        # 存储服务器发送的 RSA 公钥
        self.rsa_public_key = None
        # 是否已经发送过登录的 POST 请求（防止重复登录）
        self.has_login = False
        # 保存 checkForBothAccounts 方法可能获得的响应
        self._choose_account_response = None

    def isShowJCaptchaCode(self) -> bool:
        """
        获取用户登录时是否需要验证码。
        :return: 是否需要验证码
        """
        return self.fail_count >= 3

    def getJCaptchaCode(self) -> bytes:
        """
        获取验证码图片
        每次调用此接口时，服务器都会返回一个新的验证码。因此，不要频繁调用接口，做好缓存。
        :return: 验证码图片的二进制数据
        """
        jcaptcha = self._get("https://login.xjtu.edu.cn/cas/captcha.jpg")
        return jcaptcha.content

    def saveJCaptchaCode(self, path: str):
        """
        保存验证码图片到路径 path。此接口为了便捷提供。
        同 getJCaptchaCode，每次调用此接口时，服务器都会返回一个新的验证码。因此，请做好缓存，不要频繁调用。
        :param path: 保存验证码图片的路径
        :raise ServerError 如果服务器返回了错误信息
        """
        jcaptcha = self.getJCaptchaCode()
        with open(path, "wb") as f:
            f.write(jcaptcha)
            f.close()

    def login(self, username: str, password: str, jcaptcha: str = "", account_type: AccountType = POSTGRADUATE):
        """
        请求登录。
        请注意，此方法和 get_accounts 方法完全互斥，不能同时使用。具体正确使用示例请见类文档注释。
        :param username: 用户名，可以传入学号、手机号或邮箱
        :param password: 密码。传入明文密码即可，函数在请求前会自动加密密码。
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :param account_type: 账户的类型。如果当前登录的账号下有多种身份（比如既是本科生又是研究生），且采用手机号/邮箱登录，则需要传入此参数以选择登录的身份。否则，此参数无效。
        由于一般同时具有本科生/研究生账号时都是在读研究生，因此默认选择登录研究生账号。
        :raises ServerError: 如果登录失败，抛出此异常。异常信息中包含错误代码和错误信息。
        :raises RuntimeError: 如果已经登录过一次，则抛出此异常。请重新创建 NewLogin 对象以登录其他账号。
        """
        if self.has_login:
            raise RuntimeError("已经登录，不能重复登录。请重新创建 NewLogin 对象以登录其他账号。")

        encrypt_password = self.encrypt_password(password)
        login_response = self._post(self.post_url,
                                    data={"username": username,
                                          "password": encrypt_password,
                                          "execution": self.execution_input,
                                          "_eventId": "submit",
                                          "submit1": "Login1",
                                          "fpVisitorId": self.fp_visitor_id,
                                          "captcha": jcaptcha,
                                          "currentMenu": "1",
                                          "failN": str(self.fail_count),
                                          "mfaState": "",
                                          "geolocation": "",
                                          "trustAgent": ""}, allow_redirects=True)
        # 神人系统用返回值 401 判断是否登录失败
        if login_response.status_code == 401:
            self.fail_count += 1
            raise ServerError(401, "登录失败，用户名或密码错误。")
        else:
            login_response.raise_for_status()
            # 更加神人的是，系统在验证码错误等问题时只会返回 200，你得从返回的 html 里解析错误提示组件才知道错误是啥
            # 这系统前后端分离了，但好像也没分离
            message = extract_alert_message(login_response.text)
            if message:
                # 如果有错误提示，说明登录失败
                self.fail_count += 1
                raise ServerError(400, f"登录失败: {message['title']}")
            else:
                # 登录成功，重置失败次数
                self.fail_count = 0
                self.has_login = True
                # 检查是否出现了多账号选择页面
                account_choices = extract_account_choices(login_response.text)
                if account_choices:
                    # 如果检测到账户选择页面，根据 account_type 参数选择对应的账户
                    selected_label = None
                    if account_type == self.UNDERGRADUATE:
                        # 查找本科生账户
                        for choice in account_choices:
                            if "本科" in choice['name']:
                                selected_label = choice['label']
                                break
                    else:  # POSTGRADUATE
                        # 查找研究生账户
                        for choice in account_choices:
                            if "研究" in choice['name']:
                                selected_label = choice['label']
                                break

                    if selected_label:
                        # 提交账户选择
                        choice_response = self._post("https://login.xjtu.edu.cn/cas/login",
                                                     data={"execution": extract_execution_value(login_response.text),
                                                           "_eventId": "submit",
                                                           "geolocation": "",
                                                           "fpVisitorId": self.fp_visitor_id,
                                                           "trustAgent": "",
                                                           "username": selected_label,
                                                           "useDefault": "false"},
                                                     allow_redirects=True)
                        choice_response.raise_for_status()
                    else:
                        raise ValueError("未知的账户类型")

                    login_response = choice_response

                # 调用登录后处理函数
                self.postLogin(login_response)

        return self.session

    def postLogin(self, login_response) -> None:
        """
        此方法用于在登录后完成某些处理，比如从最终的登录响应中提取 JWT Token 并添加为 Session 的 header
        子类可以重写此方法，以完成自定义的处理工作，而无需重写整个 login 方法。
        此方法一定会在登录成功且完全结束后（自动跳转到目标网页后）被调用。
        :param login_response: 登录请求的响应对象
        :return: None。此函数的返回值不会有任何作用。
        """

    def checkForBothAccounts(self, username: str, password: str, jcaptcha: str = "") -> bool:
        """
        通过登录并检查是否存在选择账户页面，获取当前账号下是否存在多个身份（即是本科生又是研究生）。
        请注意，此方法和 login 方法完全互斥，只能选择一个调用。在调用此方法后，必须通过 finish_login 方法完成登录。
        这是因为登录系统不允许登录成功后再次尝试登录；第二次尝试会返回 404 错误。
        具体两种可用的调用方法请见本类的文档。
        :param username: 用户名，可以传入学号、手机号或邮箱
        :param password: 密码。传入明文密码即可，函数在请求前会自动加密密码。
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :return: True: 当前账户包含本科生/研究生两个身份；False：当前账户只有一个身份。
        :raises ServerError: 如果登录失败，抛出此异常。
        :raise RuntimeError: 如果已经登录过一次，则抛出此异常。请重新创建 NewLogin 对象以登录其他账号。
        (抛出 RuntimeError 说明你的程序在逻辑上存在问题：请不要同时使用两种登录方式，或在登录成功后再次调用登录方法）
        """
        if self.has_login:
            raise RuntimeError("已经登录，不能重复登录。请重新创建 NewLogin 对象以登录其他账号。")

        encrypt_password = self.encrypt_password(password)
        login_response = self._post(self.post_url,
                                    data={"username": username,
                                          "password": encrypt_password,
                                          "execution": self.execution_input,
                                          "_eventId": "submit",
                                          "submit1": "Login1",
                                          "fpVisitorId": self.fp_visitor_id,
                                          "captcha": jcaptcha,
                                          "currentMenu": "1",
                                          "failN": str(self.fail_count),
                                          "mfaState": "",
                                          "geolocation": "",
                                          "trustAgent": ""}, allow_redirects=True)
        if login_response.status_code == 401:
            self.fail_count += 1
            raise ServerError(401, "登录失败，用户名或密码错误。")
        else:
            login_response.raise_for_status()
            message = extract_alert_message(login_response.text)
            if message:
                # 如果有错误提示，说明登录失败
                self.fail_count += 1
                raise ServerError(400, f"登录失败: {message['title']}")
            else:
                self.fail_count = 0
                self.has_login = True
                account_choices = extract_account_choices(login_response.text)
                if account_choices:
                    self._choose_account_response = login_response
                    return True
                else:
                    # 没有账户选择页面，直接登录成功
                    self.postLogin(login_response)
                    return False

    def finishLogin(self, account_type: AccountType = POSTGRADUATE):
        """
        此方法和 checkForBothAccounts 方法配合使用。
        当 checkForBothAccounts 方法返回 True 时（账户存在两个身份），才需要调用此方法。如果账户只有一个身份，则不需要调用此方法。
        在无需调用时调用此方法不会有任何效果，也不会产生错误。
        """
        # 没有 checkForBothAccounts 的响应结果，说明不需要选择账户，直接返回
        if self._choose_account_response is None:
            return self.session

        account_choices = extract_account_choices(self._choose_account_response.text)
        # 如果检测到账户选择页面，根据 account_type 参数选择对应的账户
        selected_label = None
        if account_type == self.UNDERGRADUATE:
            # 查找本科生账户
            for choice in account_choices:
                if "本科" in choice['name']:
                    selected_label = choice['label']
                    break
        else:  # POSTGRADUATE
            # 查找研究生账户
            for choice in account_choices:
                if "研究" in choice['name']:
                    selected_label = choice['label']
                    break

        if selected_label:
            # 提交账户选择
            choice_response = self._post("https://login.xjtu.edu.cn/cas/login",
                                         data={"execution": extract_execution_value(self._choose_account_response.text),
                                               "_eventId": "submit",
                                               "geolocation": "",
                                               "fpVisitorId": self.fp_visitor_id,
                                               "trustAgent": "",
                                               "username": selected_label,
                                               "useDefault": "false"},
                                         allow_redirects=True)
            choice_response.raise_for_status()
        else:
            raise ValueError("未知的账户类型")

        self.postLogin(choice_response)
        return self.session

    def encrypt_password(self, password: str, public_key=None) -> str:
        """
        加密密码。采用 RSA，公钥从服务端获取。
        :param password: 明文密码
        :param public_key: 可选的公钥。如果不传入，则从服务器获取。
        :return: 加密后的密码
        """
        if public_key is None:
            if self.rsa_public_key is None:
                self.rsa_public_key = self._get("https://login.xjtu.edu.cn/cas/jwt/publicKey").text
            public_key = self.rsa_public_key

        # 加载公钥
        public_key_obj = serialization.load_pem_public_key(public_key.encode())

        # RSA 加密
        encrypted_password = public_key_obj.encrypt(
            password.encode(),
            padding.PKCS1v15()
        )

        # 转换为 base64 编码
        encrypted_password_base64 = base64.b64encode(encrypted_password).decode()

        # 添加 __RSA__ 前缀
        encoded_password = "__RSA__" + encrypted_password_base64
        return encoded_password

    def _get(self, url, **kwargs):
        """
        封装 session.get 方法。
        子类中通过重写此方法实现改变所有请求的网址为 webvpn 网址
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 请求的网址返回的内容
        """
        return self.session.get(url, **kwargs)

    def _post(self, url, **kwargs):
        """
        封装 session.post 方法。
        子类中通过重写此方法实现改变所有请求的网址为 webvpn 网址
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 请求的网址返回的内容
        """
        return self.session.post(url, **kwargs)


class NewWebVPNLogin(NewLogin):
    """
    通过 webvpn 执行的登录操作，包含登录 webvpn 和使用 webvpn 登录其他网站。
    除非登录 WebVPN 或者使用 WebVPN 访问校内网站二次登录，否则不需要使用此类。
    使用方法与 NewLogin 类似，但会自动将所有访问的网址加密为对应的 webvpn 网址。
    """
    def _get(self, url, **kwargs):
        """
        封装 session.get 方法。此方法会自动把所有访问的网址加密为对应的 webvpn 网址。
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 网址返回的内容
        """
        if not url.startswith("https://webvpn.xjtu.edu.cn"):
            encrypted = getVPNUrl(url)
        else:
            encrypted = url
        return self.session.get(encrypted, **kwargs)

    def _post(self, url, **kwargs):
        """
        封装 session.post 方法。此方法会自动把所有访问的网址加密为对应的 webvpn 网址。
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 网址返回的内容
        """
        if not url.startswith("https://webvpn.xjtu.edu.cn"):
            encrypted = getVPNUrl(url)
        else:
            encrypted = url
        return self.session.post(encrypted, **kwargs)
