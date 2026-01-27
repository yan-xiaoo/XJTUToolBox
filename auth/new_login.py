# 此文件实现了 2025 年 7 月 17 日后西安交通大学新统一认证系统的登录，即 login.xjtu.edu.cn。
# 服务端部分处理尚不稳定，因此此文件中提供的 API 也不稳定，在后续版本中可能出现函数名更改/参数更改等情况。
# 此文件会尽可能与登录页面前端实现保持一致，不会尝试利用设计漏洞等方式绕过验证码等安全措施。
import base64
import enum
import json
import re

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from lxml import html
from typing import Tuple, Optional

from .constant import EHALL_LOGIN_URL
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


def extract_mfa_enabled(html_content: str) -> bool:
    """
    从 HTML 内容中提取 globalConfig 变量的 mfaEnabled 字段（布尔值）。
    :param html_content: HTML 文本
    :return: mfaEnabled 字段的布尔值，未找到时返回 True
    """
    # 匹配 globalConfig = eval('(' + "JSON字符串" + ')');
    match = re.search(r'globalConfig\s*=\s*eval\(\'\(\'\s*\+\s*"(.*?)"\s*\+\s*\'\)\'\s*\);', html_content, re.DOTALL)
    # 默认进行 mfa 验证，不然可能有问题
    if not match:
        return True
    json_str = match.group(1)
    # 反转义
    json_str = json_str.encode('utf-8').decode('unicode_escape')
    try:
        config = json.loads(json_str)
        mfaEnabled = config.get('mfaEnabled', True)
        return mfaEnabled is True or mfaEnabled == 'true'
    except Exception:
        return True


class LoginState(enum.Enum):
    """
    登录状态枚举
    """
    REQUIRE_MFA = 0  # 需要 MFA 验证
    REQUIRE_CAPTCHA = 1  # 需要验证码
    SUCCESS = 2  # 登录成功
    FAIL = 3  # 登录失败
    REQUIRE_ACCOUNT_CHOICE = 4  # 需要选择账户


class NewLogin:
    """
    通过西安交通大学统一身份认证网站，登录目标网页。
    此类用于 2025 年 7 月 17 日后的统一认证系统，即 login.xjtu.edu.cn。
    登录系统中，存在大量“可能需要但并不强制要求”的步骤，比如：
    1. 登录失败三次后，需要输入验证码；我们无法了解之前已经错误了几次，所以这是可选的步骤。
    2. 系统可能要求我们进行 mfa 验证（两步验证），也可能不要求。
    3. 如果账号下有多种身份（比如既是本科生又是研究生），则需要选择一个身份登录。我们在登录前同样无法了解这个账号是否有多重身份，所以这是可选的步骤。
    因此，此类的 login 方法按照状态机的思想设计：
    - 首次调用时，必须传入用户名和密码。
    - 如果返回 REQUIRE_MFA，则需要进行 MFA 验证，验证完成后再次调用 login 方法继续登录流程。
    - 如果返回 REQUIRE_CAPTCHA，则需要输入验证码，输入完成后再次调用 login 方法继续登录流程。
    - 如果返回 REQUIRE_ACCOUNT_CHOICE，则需要选择账户，选择完成后再次调用 login 方法继续登录流程。
    - 如果返回 SUCCESS，则登录成功，附带 Session 对象。
    - 如果返回 FAIL，则登录失败，附带错误信息。
    通过不断调用 login 方法，直到返回 SUCCESS 或 FAIL，登录流程结束。
    此类不会自动处理验证码、MFA 验证和账户选择等步骤，而是将这些步骤交给调用者处理。
    """
    class AccountType(enum.Enum):
        UNDERGRADUATE = 0
        POSTGRADUATE = 1

    class MFAContext:
        def __init__(self, new_login_instance, state, required=True):
            self._new_login = new_login_instance
            self.state = state
            self.gid = None
            self.required = required
            self._phone_number = None

        def get_phone_number(self) -> str:
            """
            在登录系统要求两步验证时，获得绑定手机号（屏蔽中间四位）
            """
            # 缓存
            if self._phone_number is not None:
                return self._phone_number

            data = self._new_login._get("https://login.xjtu.edu.cn/cas/mfa/initByType/securephone",
                                        params={"state": self.state})
            data.raise_for_status()
            json_result = data.json()
            if json_result["code"] == 0:
                self.gid = json_result["data"]["gid"]
                self._phone_number = json_result["data"]["securePhone"]
                return self._phone_number
            else:
                raise ServerError(json_result["code"], "获得绑定手机信息失败")

        def send_verify_code(self) -> str:
            """
            在登录系统要求两步验证时，发送登录验证码到绑定手机，并返回手机号（中间屏蔽四位）
            """
            phone = self.get_phone_number()
            send_data = self._new_login._post("https://login.xjtu.edu.cn/attest/api/guard/securephone/send",
                                              json={"gid": self.gid})
            send_data.raise_for_status()
            json_result = send_data.json()
            if json_result["code"] == 0:
                return phone
            else:
                raise ServerError(json_result["code"], json_result["message"])

        def verify_phone_code(self, code: str):
            """
            在登录系统要求两步验证且发送了登录验证码后，向系统核对验证码。
            :param code: 收到的验证码
            """
            if self.gid is None:
                raise RuntimeError("必须先发送验证码才能核对验证码。")

            data = self._new_login._post("https://login.xjtu.edu.cn/attest/api/guard/securephone/valid",
                                         json={"gid": self.gid, "code": code})
            data.raise_for_status()
            json_result = data.json()
            if json_result["code"] != 0:
                raise ServerError(json_result["code"], json_result["message"])

    UNDERGRADUATE = AccountType.UNDERGRADUATE
    POSTGRADUATE = AccountType.POSTGRADUATE

    def __init__(self, login_url: str, session=None, visitor_id=None):
        """
        通过网址执行登录。
        :param login_url: 一个登录网址。在浏览器中打开此网址后，应当跳转到统一身份认证登录界面，
        且登录成功后可以返回到目标网页。
        :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
        :param visitor_id: 可选的客户端标识符。服务器通过此标识符区分登录客户端，记录客户端是否可信。如果不传入，则自动根据运行环境生成一个较为稳定的标识符。
        标识符应当为 32 位的随机十六进制数。
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
        self.fp_visitor_id = visitor_id if visitor_id is not None else generate_fp_visitor_id()
        # 是否进行 mfa 验证
        self.mfa_enabled = extract_mfa_enabled(response.text)
        # 目前服务端在本地存储登录失败次数，实现是否填写验证码的判断，我也暂时这么实现
        self.fail_count = 0
        # 存储服务器发送的 RSA 公钥
        self.rsa_public_key = None
        # 是否已经发送过登录的 POST 请求（防止重复登录）
        self.has_login = False
        # 保存 checkForBothAccounts 方法可能获得的响应
        self._choose_account_response = None
        # 两步验证上下文
        self.mfa_context: NewLogin.MFAContext | None = None
        # 登录凭据
        self._username = None
        self._password = None
        self._jcaptcha = ""

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

    def login(self, username: Optional[str] = None, password: Optional[str] = None, jcaptcha: str = "",
              account_type: AccountType = POSTGRADUATE, trust_agent=True) -> Tuple[LoginState, MFAContext | object | None]:
        """
        请求登录。
        此方法为登录流程的“驱动器”，会根据当前状态执行相应的操作。
        首次调用时，必须传入 username 和 password。
        在 MFA 验证、验证码填写或账户选择后，根据返回的状态再次调用此方法以继续登录流程。

        :param username: 用户名，可以传入学号、手机号或邮箱。仅在首次调用时需要。
        :param password: 密码。传入明文密码即可，函数在请求前会自动加密密码。仅在首次调用时需要。
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :param account_type: 账户的类型。如果当前登录的账号下有多种身份（比如既是本科生又是研究生），且采用手机号/邮箱登录，
                             在 login 返回 `REQUIRE_ACCOUNT_CHOICE` 状态后，再次调用此方法并传入此参数以选择登录的身份。否则，此参数无效。
        :param trust_agent: 是否将当前客户端标识为可信设备。默认为 True。如果不希望服务器记住当前设备，则传入 False。
        :return: 一个元组，第一个元素是登录状态（LoginState），第二个元素是附带信息。
                 - (LoginState.REQUIRE_MFA, mfa_context): 需要 MFA 验证，附带 MFA 上下文对象。MFA 验证需要调用 mfa_context 的 send_verify_code 方法发送验证码，
                   然后调用 verify_phone_code 方法验证验证码，验证完成后再次无参数的调用 login 方法继续登录流程。
                 - (LoginState.REQUIRE_CAPTCHA, None): 需要验证码。
                 - (LoginState.SUCCESS, session): 登录成功，附带 Session 对象。
                 - (LoginState.FAIL, message): 登录失败，附带错误信息。
                 - (LoginState.REQUIRE_ACCOUNT_CHOICE, choices): 需要选择账户，附带账户选项列表。
        :raises RuntimeError: 如果已经登录过一次，则抛出此异常。请重新创建 NewLogin 对象以登录其他账号。
        """
        # 如果需要选择账户，则执行账户选择逻辑
        if self._choose_account_response:
            return self._finish_account_choice(account_type)

        if self.has_login:
            raise RuntimeError("已经登录，不能重复登录。请重新创建 NewLogin 对象以登录其他账号。")

        if username and password:
            self._username = username
            self._password = self.encrypt_password(password)
            self._jcaptcha = jcaptcha
        elif not all([self._username, self._password]):
            raise ValueError("首次调用 login 时必须提供 username 和 password。")

        if self.isShowJCaptchaCode() and not jcaptcha and not self._jcaptcha:
            return LoginState.REQUIRE_CAPTCHA, None

        # MFA 检测，每次都必须执行
        # 如果上次 MFA 的结果是不需要（required=False），则需要再检测，因为说明上次是用户名-密码不对导致的问题。
        # 按原登录系统的表现，此时是需要重新检测的。
        # 如果上次的结果是需要，那么说明这次是在继续未完成的一次登录，因此不需要再检测。
        if self.mfa_enabled and not self.has_login and (self.mfa_context is None or not self.mfa_context.required):
            response = self._post("https://login.xjtu.edu.cn/cas/mfa/detect",
                                  data={"username": self._username,
                                        "password": self._password,
                                        "fpVisitorId": self.fp_visitor_id},
                                  headers={"Referer": self.post_url})
            try:
                data = response.json()
            except json.decoder.JSONDecodeError:
                raise ServerError(500, "服务器在 mfa 验证时返回了无法解析的信息")

            state = data["data"]["state"]
            need = data["data"]["need"]
            self.mfa_context = self.MFAContext(self, state, required=bool(need))

            if need:
                return LoginState.REQUIRE_MFA, self.mfa_context

        mfa_state = self.mfa_context.state if self.mfa_context else ""

        if self.mfa_context is not None and self.mfa_context.required:
            trust_agent = "true" if trust_agent else "false"
        else:
            trust_agent = ""

        login_response = self._post(self.post_url,
                                    data={"username": self._username,
                                          "password": self._password,
                                          "execution": self.execution_input,
                                          "_eventId": "submit",
                                          "submit1": "Login1",
                                          "fpVisitorId": self.fp_visitor_id,
                                          "captcha": self._jcaptcha,
                                          "currentMenu": "1",
                                          "failN": str(self.fail_count),
                                          "mfaState": mfa_state,
                                          "geolocation": "",
                                          "trustAgent": trust_agent}, allow_redirects=True)

        if login_response.status_code == 401:
            self.fail_count += 1
            return LoginState.FAIL, "登录失败，用户名或密码错误。"

        login_response.raise_for_status()
        message = extract_alert_message(login_response.text)
        if message:
            self.fail_count += 1
            return LoginState.FAIL, f"登录失败: {message['title']}"

        self.fail_count = 0
        self.has_login = True

        account_choices = extract_account_choices(login_response.text)
        if account_choices:
            self._choose_account_response = login_response
            # 登录流程尚未结束，不算完全登录
            self.has_login = False
            return LoginState.REQUIRE_ACCOUNT_CHOICE, account_choices

        self.postLogin(login_response)
        return LoginState.SUCCESS, self.session

    def _finish_account_choice(self, account_type: AccountType, trust_agent=True):
        if not self._choose_account_response:
            raise RuntimeError("当前不需要选择账户。")

        account_choices = extract_account_choices(self._choose_account_response.text)
        if account_choices is None:
            raise RuntimeError("当前不需要选择账户。")

        selected_label = None
        if account_type == self.UNDERGRADUATE:
            for choice in account_choices:
                if "本科" in choice['name']:
                    selected_label = choice['label']
                    break
        else:  # POSTGRADUATE
            for choice in account_choices:
                if "研究" in choice['name']:
                    selected_label = choice['label']
                    break

        if not selected_label:
            raise ValueError("未找到匹配的账户类型或未提供账户类型。")
        
        if self.mfa_context is not None and self.mfa_context.required:
            trust_agent = "true" if trust_agent else "false"
        else:
            trust_agent = ""

        choice_response = self._post("https://login.xjtu.edu.cn/cas/login",
                                     data={"execution": extract_execution_value(self._choose_account_response.text),
                                           "_eventId": "submit",
                                           "geolocation": "",
                                           "fpVisitorId": self.fp_visitor_id,
                                           "trustAgent": trust_agent,
                                           "username": selected_label,
                                           "useDefault": "false"},
                                     allow_redirects=True)
        choice_response.raise_for_status()

        self._choose_account_response = None
        self.has_login = True
        self.postLogin(choice_response)
        return LoginState.SUCCESS, self.session

    def postLogin(self, login_response) -> None:
        """
        此方法用于在登录后完成某些处理，比如从最终的登录响应中提取 JWT Token 并添加为 Session 的 header
        子类可以重写此方法，以完成自定义的处理工作，而无需重写整个 login 方法。
        此方法一定会在登录成功且完全结束后（自动跳转到目标网页后）被调用。
        :param login_response: 登录请求的响应对象
        :return: None。此函数的返回值不会有任何作用。
        """

    def encrypt_password(self, password: str, public_key=None) -> str:
        """
        加密密码。采用 RSA，公钥从服务端获取。
        :param password: 明文密码
        :param public_key: 可选的公钥。如果不传入，则从服务器获取。
        :return: 加密后的密码
        """
        if public_key is None:
            if self.rsa_public_key is None:
                self.rsa_public_key = self._get("https://login.xjtu.edu.cn/cas/jwt/publicKey",
                                                headers={"Referer": self.post_url}).text
            public_key = self.rsa_public_key

        # 加载公钥
        public_key_obj = RSA.import_key(public_key.encode())
        cipher = PKCS1_v1_5.new(public_key_obj)

        # RSA 加密
        encrypted_password = cipher.encrypt(password.encode())

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

    def login_or_raise(self, username: Optional[str] = None, password: Optional[str] = None, jcaptcha: str = "",
                       account_type: AccountType = POSTGRADUATE):
        """
        以单次调用的方式执行登录，如果需要额外信息则抛出异常。
        此方法是对 login 方法的封装，用于不希望处理状态机交互的场景。

        :param username: 用户名
        :param password: 密码
        :param jcaptcha: 验证码
        :param account_type: 账户类型
        :return: 登录成功后的 Session 对象。
        :raises ServerError: 登录失败或需要额外信息时抛出。此时的 ServerError 具有自定义的 error code：
        100: 登录失败，附带错误信息
        101: 需要验证码
        102: 需要 MFA 验证
        103: 需要选择账户
        500: 其他未知错误
        """
        state, info = self.login(username, password, jcaptcha, account_type)

        if state == LoginState.SUCCESS:
            return info
        elif state == LoginState.FAIL:
            raise ServerError(100, f"登录失败: {info}")
        elif state == LoginState.REQUIRE_CAPTCHA:
            raise ServerError(101, "登录需要验证码。")
        elif state == LoginState.REQUIRE_MFA:
            raise ServerError(102, "登录需要 MFA 验证。")
        elif state == LoginState.REQUIRE_ACCOUNT_CHOICE:
            raise ServerError(103, "登录需要选择账户。")
        else:
            raise ServerError(500, "未知的登录状态。")


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
