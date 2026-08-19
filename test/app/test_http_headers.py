import unittest
from types import SimpleNamespace

from app.sessions.campus_card_session import CampusCardSession
from app.sessions.common_session import http_safe_headers


class HttpSafeHeadersTest(unittest.TestCase):
    def test_drops_non_latin1_values(self):
        safe = http_safe_headers({
            "Synjones-Auth": "bearer token",
            "X-Card-Name": "张三",
            "synAccessSource": "h5",
        })
        self.assertEqual(safe["Synjones-Auth"], "bearer token")
        self.assertEqual(safe["synAccessSource"], "h5")
        self.assertNotIn("X-Card-Name", safe)


class CampusCardAuthFailureTest(unittest.TestCase):
    def test_json_401_other_device_is_auth_failure(self):
        session = CampusCardSession()
        response = SimpleNamespace(
            headers={"Content-Type": "application/json"},
            text='{"code":401,"message":"已经在其他设备登录"}',
            json=lambda: {"code": 401, "message": "已经在其他设备登录"},
        )
        self.assertTrue(session.is_auth_failure_response(response))


if __name__ == "__main__":
    unittest.main()
