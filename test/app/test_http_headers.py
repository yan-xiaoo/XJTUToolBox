import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.sessions import common_session
from app.sessions.campus_card_session import CampusCardSession
from app.sessions.session_backend import AccessMode
from app.utils.session_persistence import SiteSnapshot
from auth import ServerError
from auth.constant import MOBILE_BROWSER_UA


def _response(payload=None, *, ok=True, error=None):
    response = SimpleNamespace(
        ok=ok,
        headers={"Content-Type": "application/json"},
        text="",
    )
    response.json = Mock(side_effect=error) if error else Mock(return_value=payload)
    return response


def _profile_payload(code=200, **overrides):
    data = {
        "name": "Test User",
        "sno": "student-id",
        "cardAccount": "card-id",
    }
    data.update(overrides)
    return {"code": code, "data": data}


def _logged_in_session():
    session = CampusCardSession()
    session.post = Mock(return_value=_response({"access_token": "test-token"}))
    session.get = Mock(return_value=_response(_profile_payload()))
    if not session._try_ticket("https://ncard.xjtu.edu.cn/?ticket=test-ticket"):
        raise AssertionError("synthetic campus-card login did not complete")
    return session


class CampusCardHeaderTest(unittest.TestCase):
    def test_common_session_has_no_global_header_filter(self):
        self.assertFalse(hasattr(common_session, "http_safe_headers"))

    def test_login_state_contains_only_real_site_headers(self):
        session = _logged_in_session()

        self.assertEqual(dict(session.headers), {
            "Synjones-Auth": "bearer test-token",
            "synAccessSource": "h5",
        })
        session.get.assert_called_once_with(
            session.USER_URL,
            timeout=15,
            _skip_auth_check=True,
        )

    def test_request_sends_only_real_site_headers_and_mobile_user_agent(self):
        session = _logged_in_session()
        session.get = CampusCardSession.get.__get__(session)
        session.backend.session.headers.clear()
        session.backend.session.request = Mock(return_value=_response({}))

        session.get("https://ncard.xjtu.edu.cn/test", _skip_auth_check=True)

        self.assertEqual(session.backend.session.request.call_args.kwargs["headers"], {
            "Synjones-Auth": "bearer test-token",
            "synAccessSource": "h5",
            "User-Agent": MOBILE_BROWSER_UA,
        })

    def test_snapshot_restores_token_then_reloads_profile(self):
        source = _logged_in_session()

        snapshot = source.to_site_snapshot()

        self.assertEqual(snapshot.headers, {
            "Synjones-Auth": "bearer test-token",
            "synAccessSource": "h5",
        })
        restored = CampusCardSession()
        restored.restore_site_snapshot(snapshot)
        self.assertEqual(restored.access_token, "test-token")
        self.assertEqual(restored.user_name, "")
        self.assertEqual(restored.student_no, "")
        self.assertEqual(restored.card_account, "")

        restored.get = Mock(side_effect=[
            _response({"code": 200}),
            _response(_profile_payload()),
        ])
        self.assertTrue(restored.validate_login())
        self.assertEqual(restored.user_name, "Test User")
        self.assertEqual(restored.student_no, "student-id")
        self.assertEqual(restored.card_account, "card-id")
        self.assertEqual(restored.get.call_count, 2)

    def test_restore_discards_legacy_pseudo_headers(self):
        snapshot = SiteSnapshot(
            site_key="campus_card",
            access_mode=AccessMode.NORMAL.value,
            headers={
                "Synjones-Auth": "bearer test-token",
                "synAccessSource": "h5",
                "X-Card-Access-Token": "legacy-token",
                "X-Card-Name": "Legacy User",
                "X-Card-Sno": "legacy-student-id",
                "X-Card-Account": "legacy-card-id",
            },
            saved_at=1.0,
        )

        restored = CampusCardSession()
        restored.restore_site_snapshot(snapshot)

        self.assertEqual(restored.access_token, "test-token")
        self.assertEqual(restored.user_name, "")
        self.assertEqual(restored.student_no, "")
        self.assertEqual(restored.card_account, "")
        self.assertFalse(any(key.lower().startswith("x-card-") for key in restored.headers))


class CampusCardProfileTest(unittest.TestCase):
    def test_profile_accepts_integer_string_and_absent_success_code(self):
        for payload in (
            _profile_payload(200),
            _profile_payload("200"),
            {"data": _profile_payload()["data"]},
        ):
            with self.subTest(payload=payload):
                session = CampusCardSession()
                session.get = Mock(return_value=_response(payload))

                session._load_user_profile()

                self.assertEqual(session.user_name, "Test User")
                self.assertEqual(session.student_no, "student-id")
                self.assertEqual(session.card_account, "card-id")

    def test_profile_rejects_invalid_http_json_business_and_field_shapes(self):
        cases = (
            _response(_profile_payload(), ok=False),
            _response(error=ValueError("broken")),
            _response(["not", "an", "object"]),
            _response(_profile_payload(500)),
            _response({"code": 200}),
            _response({"code": 200, "data": []}),
            _response(_profile_payload(name="")),
            _response(_profile_payload(sno="")),
            _response(_profile_payload(cardAccount="")),
        )
        for response in cases:
            with self.subTest(response=response):
                session = CampusCardSession()
                session.get = Mock(return_value=response)

                with self.assertRaisesRegex(ServerError, "校园卡用户资料"):
                    session._load_user_profile()

    def test_ticket_exchange_rejects_invalid_profile_before_login_succeeds(self):
        session = CampusCardSession()
        session.post = Mock(return_value=_response({"access_token": "test-token"}))
        session.get = Mock(return_value=_response({"code": 200, "data": {}}))

        with self.assertRaisesRegex(ServerError, "校园卡用户资料"):
            session._try_ticket("https://ncard.xjtu.edu.cn/?ticket=test-ticket")

        self.assertFalse(session.has_login)

    def test_restored_valid_token_propagates_profile_failure(self):
        session = CampusCardSession()
        session.restore_site_snapshot(SiteSnapshot(
            site_key="campus_card",
            access_mode=AccessMode.NORMAL.value,
            headers={
                "Synjones-Auth": "bearer test-token",
                "synAccessSource": "h5",
            },
            saved_at=1.0,
        ))
        session.get = Mock(side_effect=[
            _response({"code": "200"}),
            _response({"code": 500, "data": {}}),
        ])

        with self.assertRaisesRegex(ServerError, "校园卡用户资料"):
            session.validate_login()


class CampusCardAuthFailureTest(unittest.TestCase):
    def test_json_401_other_device_is_auth_failure(self):
        session = CampusCardSession()
        response = _response({"code": 401, "message": "已经在其他设备登录"})
        response.text = '{"code":401,"message":"已经在其他设备登录"}'

        self.assertTrue(session.is_auth_failure_response(response))

    def test_json_string_401_is_auth_failure(self):
        session = CampusCardSession()
        response = _response({"code": "401", "message": "expired"})
        response.text = '{"code":"401","message":"expired"}'

        self.assertTrue(session.is_auth_failure_response(response))


if __name__ == "__main__":
    unittest.main()
