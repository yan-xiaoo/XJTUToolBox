import datetime

import requests
from auth import Login, JWAPP_URL, ServerError
from auth.new_login import NewLogin, extract_alert_message


class JwappLogin(Login):
    """移动教务系统的登录类。此系统和考勤系统类似，都需要在登录后，从 header 中添加一个 token"""

    def __init__(self, session=None):
        super().__init__(JWAPP_URL, session=session)

    def post_login(self) -> requests.Session:
        """
        登录并添加 token 到 session 头部
        :raise ServerError，如果服务器返回错误信息
        :return: session 对象，其实就是 requests.Session 对象
        """
        self.getUserIdentity()
        url = self.getRedirectUrl()
        response = self._get(url)
        token = response.url.split("token=")[1].split('&')[0]
        self.session.headers.update({"Authorization": token})
        return self.session


class JwappNewLogin(NewLogin):
    """移动教务系统的登录类。此系统和考勤系统类似，都需要在登录后，从 header 中添加一个 token"""

    def __init__(self, session=None):
        super().__init__(JWAPP_URL, session=session)

    def login(self, username, password, jcaptcha="") -> requests.Session:
        """
        登录并添加 token 到 session 头部
        :return: session 对象，其实就是 requests.Session 对象
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
                try:
                    token = login_response.url.split("token=")[1].split('&')[0]
                except IndexError:
                    raise ServerError(500, "服务器出现内部错误。")
                self.session.headers.update({"Authorization": token})

        return self.session


def jwapp_fast_login(username: str, password: str, captcha="", session=None):
    """
    快速登录移动教务系统。此函数仅仅是为了方便的封装。
    此函数会尝试直接登录，发现需要验证码时，把验证码下载到当前目录下的 captcha.png 文件中，并且用 input 函数等待输入验证码。

    :param username: 用户名
    :param password: 密码
    :param captcha: 验证码。此参数不一定需要传入；需要验证码时，会使用 input 让用户输入。
    :param session: 自定义的 Session 对象。默认利用 get_session 函数生成一个修改了 UA 的空 Session。
    :return: 登录成功后的 Session 对象
    """
    login = JwappLogin(session)
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


class JwappUtil:
    """
    此类封装了一系列移动教务系统通用接口。
    系统对同一个 session 的连接可能存在时间限制。因此，尽量不要持久性的存储此类的对象；每次使用时重新获取一个登录的 session，然后重新创建此对象。
    """

    def __init__(self, session):
        self.session = session
        self._termNo = None
        self._basisData = None

    def getTimeTableBasis(self):
        """获得一些关于课表的基本信息。
        :raises ServerError: 如果服务器返回错误信息
        返回实例如下：
        {
           "msg": "操作成功",
           "code": 200,
           "xnxqdm": "2023-2024-2",
           "maxWeekNum": 18,
           "maxSection": 11,
           "weekCalendar": ["2024-06-03:周一", "2024-06-04:周二", "2024-06-05:周三", "2024-06-06:周四", "2024-06-07:周五", "2024-06-08:周六", "2024-06-09:周日"],
           "todayWeekDay": 1,
           "todayWeekNum": 15,
           "xnxqmc": "2023-2024学年 第二学期"
        }
        """
        response = self._get("https://jwapp.xjtu.edu.cn/api/biz/v410/common/school/time")
        result = response.json()
        if result["code"] != 200:
            raise ServerError(result["code"], result["msg"])
        else:
            self._basisData = result
            return result

    def getBeginOfTerm(self) -> datetime.date:
        if self._basisData is None:
            self.getTimeTableBasis()

        return (datetime.date.today() -
                datetime.timedelta(days=7*(self._basisData["todayWeekNum"]-1)+self._basisData["todayWeekDay"]-1))

    def getCurrentTerm(self):
        """获得当前学期的字符串表示形式，比如 2022-2023-1"""
        result = self.getTimeTableBasis()
        return result["xnxqdm"]

    def _get(self, url, **kwargs):
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url, **kwargs):
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
