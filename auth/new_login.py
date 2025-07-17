# 此文件实现了 2025 年 7 月 17 日后西安交通大学新统一认证系统的登录，即 login.xjtu.edu.cn。
# 服务端部分处理尚不稳定，因此此文件中提供的 API 也不稳定，在后续版本中可能出现函数名更改/参数更改等情况。
# 此文件会尽可能与登录页面前端实现保持一致，不会尝试利用设计漏洞等方式绕过验证码等安全措施。
import base64
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
    """

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

    def login(self, username: str, password: str, jcaptcha: str = ""):
        """
        请求登录
        :param username: 用户名
        :param password: 密码。传入明文密码即可，函数在请求前会自动加密密码。
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :raises ServerError: 如果登录失败，抛出此异常。异常信息中包含错误代码和错误信息。
        """
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
