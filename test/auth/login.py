import unittest

from auth import JWXT_LOGIN_URL, WEBVPN_LOGIN_URL
from auth.new_login import NewLogin

# 为了进行此测试，您需要拥有西安交通大学统一身份认证登录的账号
# 请将账号的用户名与密码填写在下方，然后执行测试
# 用户名与密码仅会用于登录西安交通大学相关的系统，不会被记录或发送到其他任何服务器。

USERNAME = ""
PASSWORD = ""


class TestLogin(unittest.TestCase):
    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_login(self):
        """测试访问教务系统的连通性"""
        login = NewLogin(JWXT_LOGIN_URL)
        self.assertIsNotNone(login.login(USERNAME, PASSWORD))

    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_webvpn_login(self):
        """测试 webvpn 访问知网的连通性"""
        login = NewLogin(WEBVPN_LOGIN_URL)
        session = login.login(USERNAME, PASSWORD)
        response = session.get("https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI=")
        self.assertTrue(response.ok)
        # 知网需要再点一下 IP 登录，所以直接得到的界面只有登录界面
        self.assertIn("<title>中国知网-登录", response.content.decode("utf-8"))


if __name__ == '__main__':
    unittest.main()
