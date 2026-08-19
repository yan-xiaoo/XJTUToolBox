import unittest

from app.sessions.common_session import http_safe_headers


class HttpSafeHeadersTest(unittest.TestCase):
    def test_drops_non_latin1_values(self):
        safe = http_safe_headers({
            "User-Agent": "Mozilla/5.0",
            "X-Card-Name": "张三",
            "Referer": "http://rg.lib.xjtu.edu.cn:8086/seat/",
        })
        self.assertEqual(safe["User-Agent"], "Mozilla/5.0")
        self.assertEqual(safe["Referer"], "http://rg.lib.xjtu.edu.cn:8086/seat/")
        self.assertNotIn("X-Card-Name", safe)


if __name__ == "__main__":
    unittest.main()
