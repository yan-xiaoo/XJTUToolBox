import unittest

from auth import ServerError, getVPNUrl, getOrdinaryUrl


class TestAuthUtils(unittest.TestCase):
    def test_servererror(self):
        error = ServerError(-1, "test")
        self.assertEqual(error.code, -1)
        self.assertEqual(error.message, "test")
        self.assertEqual(str(error), "ServerError: -1 test")
        error2 = ServerError.from_json({"code": -1, "message": "test"})
        self.assertEqual(error2.code, -1)
        self.assertEqual(error2.message, "test")
        self.assertEqual(str(error2), "ServerError: -1 test")

    def test_getvpnurl(self):
        url = "https://kns.cnki.net/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI="
        vpn_url = getVPNUrl(url)
        self.assertEqual(vpn_url, "https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI=")

    def test_ordinaryurl(self):
        vpn_url = "https://webvpn.xjtu.edu.cn/https/77726476706e69737468656265737421fbf952d2243e635930068cb8/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI="
        ordinary_url = getOrdinaryUrl(vpn_url)
        self.assertEqual(ordinary_url, "https://kns.cnki.net/KCMS/detail/detail.aspx?dbcode=CJFQ&dbname=CJFD2007&filename=JEXK200702000&uid=WEEvREcwSlJHSldRa1FhcTdnTnhXY20wTWhLQWVGdmJFOTcvMFFDWDBycz0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&v=MTYzNjU3cWZaT2RuRkNuaFZMN0tMeWpUWmJHNEh0Yk1yWTlGWklSOGVYMUx1eFlTN0RoMVQzcVRyV00xRnJDVVI=")


if __name__ == '__main__':
    unittest.main()
