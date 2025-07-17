import base64
import typing

import requests
from Crypto.Cipher import AES

from .util import get_session, ServerError, get_timestamp, getVPNUrl

PUBLIC_KEY = "0725@pwdorgopenp"


class Login:
    """
    通过西安交通大学统一身份认证网站，登录目标网页。
    此类用于 2025 年 7 月 17 日前的统一认证系统，即 org.xjtu.edu.cn/openplatform/login.html。
    对于统一身份认证网站登录的具体方式，请见 https://yan-xiaoo.github.io/blog/2024/02/24/%E8%A5%BF%E5%AE%89%E4%BA%A4%E9%80%9A%E5%A4%A7%E5%AD%A6%E7%99%BB%E5%BD%95%E7%B3%BB%E7%BB%9F%E8%87%AA%E5%8A%A8%E5%8C%96
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
        self._get(login_url)

        # 如果按照正确的方式调用接口的话，这些成员变量会被用来跨方法传递某些请求需要的数据。
        self.memberId = None
        self.userType = None
        self.personNo = None

    def isShowJCaptchaCode(self, username: str) -> bool:
        """
        获取用户登录时是否需要验证码。
        :param username: 用户名
        :return: 是否需要验证码
        :raise ServerError 如果服务器返回了错误信息
        """
        is_show_jcaptcha = self._post("https://org.xjtu.edu.cn/openplatform/g/admin/getIsShowJcaptchaCode",
                                      headers={'Content-Type': 'application/json;charset=UTF-8'},
                                      json={"userName": username})
        is_show_jcaptcha_json = is_show_jcaptcha.json()
        if is_show_jcaptcha_json["code"] == 0:
            return is_show_jcaptcha_json["data"]
        else:
            raise ServerError.from_json(is_show_jcaptcha_json)

    def getJCaptchaCode(self) -> bytes:
        """
        获取验证码图片
        每次调用此接口时，服务器都会返回一个新的验证码。因此，不要频繁调用接口，做好缓存。
        :return: 验证码图片的二进制数据
        :raise ServerError 如果服务器返回了错误信息
        """
        jcaptcha = self._post("https://org.xjtu.edu.cn/openplatform/g/admin/getJcaptchaCode",
                              headers={'Content-Type': 'application/json;charset=UTF-8'})
        jcaptcha_json = jcaptcha.json()
        if jcaptcha_json["code"] == 0:
            return base64.b64decode(jcaptcha_json["data"])
        else:
            raise ServerError.from_json(jcaptcha_json)

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

    def login(self, username: str, password: str, jcaptcha: str = "") -> typing.Dict:
        """
        请求登录

        :param username: 用户名
        :param password: 密码。传入明文密码即可，函数在请求前会自动加密密码。
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :raise ServerError 如果服务器返回了错误信息
        :return: 登录成功后的 JSON 数据。具体格式：
        {
            "pwdState": "2",
            "tokenKey": "user_token_..."
            "orgInfo": {
                "logo": null,
                "orgId": 1000,
                "orgName": "西安交通大学",
                "memberId": ...(整数）,
                "firstLogin": 2,
                "isIdentification": 1,
                "memberName": null,
                "addNew": 2
        }
        """
        login_response = self._post("https://org.xjtu.edu.cn/openplatform/g/admin/login",
                                    headers={"Content-Type": "application/json;charset=utf-8"},
                                    json={"loginType": 1,
                                          "username": username,
                                          "pwd": self.encrypt_password(password),
                                          "jcaptchaCode": jcaptcha})
        login_json = login_response.json()
        if login_json["code"] == 0:
            # 模仿网站的行为，手动设置两个 cookie
            open_platform_user = str(login_json["data"]["tokenKey"])
            memberId = str(login_json["data"]["orgInfo"]["memberId"])
            self.session.cookies.set("open_Platform_User", open_platform_user)
            self.session.cookies.set("memberId", memberId)
            self.memberId = memberId
            return login_json["data"]
        else:
            raise ServerError.from_json(login_json)

    def getUserIdentity(self, memberId: str = None) -> typing.Dict:
        """
        获得用户的身份。此接口必须在调用 login 成功后调用.

        :param memberId: 成员的组织。使用 login 函数登录后，可以不填此参数。
        :return: 用户相关信息。其中被其他接口使用的信息会被自动保存在成员变量中。
        返回内容示例：
        {
            "personNo": "...",
            "userType": 1,
            "payCard": "",
            "railwaystationstart": "",
            "railwaystationstartName": "",
            "railwaystation": "",
            "railwaystationName": "",
            "id": null
        }
        :raise ServerError 如果服务器返回了错误信息
        """
        if memberId is None:
            memberId = self.memberId

        identity_response = self._post("https://org.xjtu.edu.cn/openplatform/g/admin/getUserIdentity",
                                       headers={
                                           "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                                       data={"memberId": memberId})
        identity_json = identity_response.json()
        if identity_json["code"] == 0:
            self.userType = identity_json["data"][0]["userType"]
            self.personNo = identity_json["data"][0]["personNo"]
            return identity_json["data"][0]
        else:
            raise ServerError.from_json(identity_json)

    def getRedirectUrl(self, userType=None, personNo=None) -> str:
        """
        获取重定向地址。此接口必须在调用 getUserIdentity 成功后调用。

        :param userType: 用户类型。使用 getUserIdentity 函数后，可以不填此参数。
        :param personNo: 用户编号。使用 getUserIdentity 函数后，可以不填此参数。
        :return: 重定向地址
        :raise ServerError 如果服务器返回了错误信息
        """
        url_response = self._get("https://org.xjtu.edu.cn/openplatform/oauth/auth/getRedirectUrl",
                                 headers={"Content-Type": "application/json;charset=utf-8"},
                                 params={"userType": userType or self.userType,
                                         "personNo": personNo or self.personNo,
                                         "_": get_timestamp()})
        url_json = url_response.json()
        if url_json["code"] == 0:
            return url_json["data"]
        else:
            raise ServerError.from_json(url_json)

    def post_login(self) -> requests.Session:
        """
        调用此函数，可以一站式完成登录结束后的重定向工作。
        :return: 登录成功后的 Session 对象（其实就是 self.session）
        :raise ServerError 如果服务器在任何一步返回了错误信息
        """
        self.getUserIdentity()
        url = self.getRedirectUrl()
        self.session.get(url)
        return self.session

    @staticmethod
    def encrypt_password(password: str) -> str:
        """
        加密密码。采用 AES256-ECB, 密钥为固定的 0725@pwdorgopenp。
        :param password: 明文密码
        :return: 加密后的密码
        """

        def pad(text):
            text_length = len(text)
            amount_to_pad = AES.block_size - (text_length % AES.block_size)
            if amount_to_pad == 0:
                amount_to_pad = AES.block_size
            padding = chr(amount_to_pad)
            return text + padding * amount_to_pad

        cipher = AES.new(
            PUBLIC_KEY.encode('utf-8'),
            AES.MODE_ECB
        )

        encrypted_data = cipher.encrypt(pad(password).encode('utf-8'))
        return str(base64.b64encode(encrypted_data), encoding='utf-8')

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


class WebVPNLogin(Login):
    """通过 webvpn 执行的登录操作，包含登录 webvpn 和使用 webvpn 登录其他网站。
    可能是为了解决跨域问题，webvpn 中设置 cookie 需要请求特定接口而非直接在浏览器存储，因此，
    webvpn 上执行的登录和一般的登录有所差别。
    除非登录 WebVPN 或者使用 WebVPN 访问校内网站二次登录，否则不需要使用此类。"""

    def login(self, username: str, password: str, jcaptcha: str = "") -> typing.Dict:
        """
        请求登录。此函数会在登录成功后，自动设置 webvpn 的 cookie。
        :param username: 用户名
        :param password: 密码
        :param jcaptcha: 验证码。如果 isShowJCaptchaCode 返回 False，则不用传入此参数。否则，需要传入验证码字符串。
        :raise ServerError 如果服务器返回了错误信息
        :return: 登录成功后的 JSON 数据。具体格式：
        {
            "pwdState": "2",
            "tokenKey": "user_token_..."
            "orgInfo": {
                "logo": null,
                "orgId": 1000,
                "orgName": "西安交通大学",
                "memberId": ...(整数）,
                "firstLogin": 2,
                "isIdentification": 1,
                "memberName": null,
                "addNew": 2
        }
        """
        login_response = self._post("https://org.xjtu.edu.cn/openplatform/g/admin/login",
                                    headers={"Content-Type": "application/json;charset=utf-8"},
                                    json={"loginType": 1,
                                          "username": username,
                                          "pwd": self.encrypt_password(password),
                                          "jcaptchaCode": jcaptcha})
        login_json = login_response.json()
        if login_json["code"] == 0:
            # 模仿网站的行为，手动设置两个 cookie
            open_platform_user = str(login_json["data"]["tokenKey"])
            memberId = str(login_json["data"]["orgInfo"]["memberId"])
            self.memberId = memberId
            self._set_cookie("open_Platform_User", open_platform_user)
            self._set_cookie("memberId", memberId)
            return login_json["data"]
        else:
            raise ServerError.from_json(login_json)

    def _get(self, url, **kwargs):
        """
        封装 session.get 方法。此方法会自动把所有访问的网址加密为对应的 webvpn 网址。
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 网址返回的内容
        """
        encrypted = getVPNUrl(url)
        return self.session.get(encrypted, **kwargs)

    def _post(self, url, **kwargs):
        """
        封装 session.post 方法。此方法会自动把所有访问的网址加密为对应的 webvpn 网址。
        :param url: 请求的网址
        :param kwargs: 其他参数
        :return: 网址返回的内容
        """
        encrypted = getVPNUrl(url)
        return self.session.post(encrypted, **kwargs)

    def _set_cookie(self, name, value, host="org.xjtu.edu.cn", path="/openplatform/login.html", scheme="https"):
        """
        设置 cookie。此方法会在 webvpn 上设置 cookie。
        :param name: cookie 名
        :param value: cookie 值
        :param host: cookie 主机。一般为 org.xjtu.edu.cn
        :param path: cookie 路径。一般为 /openplatform/login.html
        :param scheme: 协议。一般为 https。
        :return:
        """
        self.session.post("https://webvpn.xjtu.edu.cn/wengine-vpn/cookie",
                          params={
                              "method": "set",
                              "host": host,
                              "scheme": scheme,
                              "path": path,
                              "ck_data": f"{name}={value}; path=/;"
                          })


def _fast_login(login_class, url: str, username: str, password: str, captcha="", session=None):
    if not issubclass(login_class, Login):
        raise TypeError("login_class 必须是 Login 的子类")
    login = login_class(url, session)
    if login.isShowJCaptchaCode(username):
        # 需要验证码，让用户输入
        if captcha == "":
            login.saveJCaptchaCode("captcha.png")
            print("您需要输入验证码。请打开运行程序目录下的 captcha.png 文件，并输入验证码。")
            captcha = input("请输入验证码：")
        login.login(username, password, captcha)
    else:
        login.login(username, password)

    return login.post_login()


def fast_login(url: str, username: str, password: str, captcha="", session=None):
    """
    快速登录。此函数仅仅是为了方便的封装，如果需要定制，请自行使用 Login 类的接口。
    此函数会尝试直接登录，发现需要验证码时，把验证码下载到当前目录下的 captcha.png 文件中，并且用 input 函数等待输入验证码。

    :param url: 登录网址
    :param username: 用户名
    :param password: 密码
    :param captcha: 验证码。此参数不一定需要传入；需要验证码时，会使用 input 让用户输入。
    :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
    :return: 登录成功后的 Session 对象
    """
    return _fast_login(Login, url, username, password, captcha, session)


def webvpn_fast_login(url: str, username: str, password: str, captcha="", session=None):
    """
    快速登录。此函数仅仅是为了方便的封装，如果需要定制，请自行使用 WebVPNLogin 类的接口。
    此函数会尝试直接登录，发现需要验证码时，把验证码下载到当前目录下的 captcha.png 文件中，并且用 input 函数等待输入验证码。

    :param url: 登录网址
    :param username: 用户名
    :param password: 密码
    :param captcha: 验证码。此参数不一定需要传入；需要验证码时，会使用 input 让用户输入。
    :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
    :return: 登录成功后的 Session 对象
    """
    return _fast_login(WebVPNLogin, url, username, password, captcha, session)


def check_password(username: str, password: str) -> bool:
    """
    检查用户名和密码是否正确。此函数会前往不带 appid 的西安交通大学统一身份认证登录网页，尝试使用给定的用户名与密码登录，
    并检查返回信息。如果返回「没有 appID」，说明用户名-密码正确。如果返回「用户名或密码错误」，说明用户名-密码错误。
    此函数不处理需要验证码的情况。
    :param username: 用户名
    :param password: 密码
    :return: True: 用户名-密码正确。False:用户名-密码错误。
    """
    login = Login("https://org.xjtu.edu.cn/openplatform/login.html")
    try:
        login.login(username, password)
    except ServerError as e:
        if e.code == -1:
            return True
        else:
            return False
