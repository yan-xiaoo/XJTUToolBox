import unittest

from auth import Login, WebVPNLogin, fast_login, webvpn_fast_login, EHALL_LOGIN_URL, WEBVPN_LOGIN_URL, BB_LOGIN_URL, \
    check_password


# 为了进行此测试，您需要拥有西安交通大学统一身份认证登录的账号
# 请将账号的用户名与密码填写在下方，然后执行测试
# 用户名与密码仅会用于登录西安交通大学相关的系统，不会被记录或发送到其他任何服务器。

USERNAME = ""
PASSWORD = ""


class TestLogin(unittest.TestCase):
    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_login(self):
        """测试访问 EHALL 的连通性"""
        login = Login(EHALL_LOGIN_URL)
        self.assertFalse(login.isShowJCaptchaCode(USERNAME))
        self.assertTrue(login.login(USERNAME, PASSWORD))
        login.post_login()

    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_webvpn_login(self):
        """测试 webvpn 访问知网的连通性"""
        login = WebVPNLogin(WEBVPN_LOGIN_URL)
        self.assertFalse(login.isShowJCaptchaCode(USERNAME))
        self.assertTrue(login.login(USERNAME, PASSWORD))
        session = login.post_login()
        response = session.get("https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI=")
        self.assertTrue(response.ok)
        self.assertIn("<title>信息安全综述 - 中国知网", response.text)

    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_fast_login(self):
        """测试快速登录。测试连接思源学堂的可用性。"""
        session = fast_login(BB_LOGIN_URL, USERNAME, PASSWORD)
        response = session.get("https://bb.xjtu.edu.cn/")
        self.assertTrue(response.ok)
        self.assertNotIn("西安交通大学统一身份认证", response.text)

    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_webvpn_fast_login(self):
        """测试 webvpn 访问知网的连通性"""
        session = webvpn_fast_login(WEBVPN_LOGIN_URL, USERNAME, PASSWORD)
        response = session.get(
            "https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI=")
        self.assertTrue(response.ok)
        self.assertIn("<title>信息安全综述 - 中国知网", response.text)

    @unittest.skipIf(not USERNAME or not PASSWORD, "用户名与密码未提供")
    def test_check_password(self):
        """测试「检查用户名密码正确性」的函数是否正确。"""
        self.assertTrue(check_password(USERNAME, PASSWORD))
        self.assertFalse(check_password(USERNAME, PASSWORD + '1'))


if __name__ == '__main__':
    unittest.main()
