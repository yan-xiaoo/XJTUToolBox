import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from auth import ServerError
from auth.constant import FITNESS_LOGIN_URL
from app.sessions.fitness_session import FitnessSession
from app.sessions.session_backend import AccessMode


def _response(url="https://tyxylp.xjtu.edu.cn/callback", *, ok=True, payload=None, error=None):
    response = SimpleNamespace(url=url, ok=ok)
    response.json = Mock(side_effect=error) if error else Mock(return_value=payload)
    response.headers = {"Content-Type": "application/json"}
    response.text = ""
    return response


def _callback(**overrides):
    values = {
        "timestamp": "1",
        "nonce": "2",
        "course_id": "3",
        "uid": "4",
        "card_id": "5",
        "login_type": "6",
        "type": "7",
        "school_id": "8",
        "student_num": "9",
        "user_type": "10",
        "token": "token",
        "sign": "signature",
        "term_id": "11",
        "id": "12",
    }
    values.update(overrides)
    return "https://tyxylp.xjtu.edu.cn/callback?" + "&".join(f"{key}={value}" for key, value in values.items())


class FitnessLoginTest(unittest.TestCase):
    def _session(self):
        session = FitnessSession()
        session.reset_timeout = Mock()
        return session

    def test_cas_login_uses_correct_url_and_disables_qrcode(self):
        session = self._session()
        captured = {}

        def perform(*args, **kwargs):
            captured.update(kwargs)

        session.perform_cas_login = perform
        session.get = Mock(return_value=_response(_callback()))
        session.post = Mock(return_value=_response(payload={"status": 1}))

        with patch("app.sessions.fitness_session.NewLogin", return_value=object()) as login_type:
            session._login("user", "password")
            captured["password_login_factory"]()

        login_type.assert_called_once()
        self.assertEqual(login_type.call_args.args[0], FITNESS_LOGIN_URL)
        self.assertIsNone(captured["qrcode_login_factory"])
        self.assertFalse(captured["allow_qrcode_login"])

    def test_valid_callback_and_check_login_initialize_state(self):
        session = self._session()
        session.perform_cas_login = Mock()
        session.get = Mock(return_value=_response(_callback()))
        session.post = Mock(return_value=_response(payload={"status": 1}))

        session._login("user", "password")

        self.assertTrue(session.has_login)
        self.assertEqual(session.referer_url, _callback())
        self.assertEqual(session.headers["X-Fitness-Referer"], _callback())
        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["headers"]["X-Requested-With"], "XMLHttpRequest")
        self.assertEqual(kwargs["headers"]["Referer"], _callback())

    def test_wrong_suffix_spoofed_and_query_only_hosts_are_rejected(self):
        for url in (
            "https://evil.example/callback?next=tyxylp.xjtu.edu.cn",
            "https://tyxylp.xjtu.edu.cn.evil.com/callback",
            "https://evil.com/tyxylp.xjtu.edu.cn/callback",
        ):
            with self.subTest(url=url):
                session = self._session()
                session.perform_cas_login = Mock()
                session.get = Mock(return_value=_response(url))
                with self.assertRaises(ServerError):
                    session._login("user", "password")
                self.assertFalse(session.has_login)

    def test_missing_token_or_signature_is_rejected(self):
        for missing in ("token", "sign"):
            with self.subTest(missing=missing):
                session = self._session()
                session.perform_cas_login = Mock()
                session.get = Mock(return_value=_response(_callback(**{missing: ""})))
                with self.assertRaises(ServerError):
                    session._login("user", "password")

    def test_check_login_http_json_shape_and_status_failures(self):
        cases = (
            _response(payload={"status": 0}),
            _response(ok=False, payload={"status": 1}),
            _response(payload=["not", "object"]),
            _response(error=ValueError("broken")),
        )
        for check_response in cases:
            with self.subTest(response=check_response):
                session = self._session()
                session.perform_cas_login = Mock()
                session.get = Mock(return_value=_response(_callback()))
                session.post = Mock(return_value=check_response)
                with self.assertRaises(ServerError):
                    session._login("user", "password")


class FitnessValidationTest(unittest.TestCase):
    def test_validate_login_matrix(self):
        cases = (
            (_response(payload={"status": 1}), True),
            (_response(payload={"status": 0}), False),
            (_response(payload=["not", "object"]), False),
            (_response(error=ValueError("broken")), False),
            (requests.ConnectionError("offline"), False),
        )
        for response_or_error, expected in cases:
            with self.subTest(response=response_or_error):
                session = FitnessSession()
                if isinstance(response_or_error, Exception):
                    session.post = Mock(side_effect=response_or_error)
                else:
                    session.post = Mock(return_value=response_or_error)
                self.assertIs(session.validate_login(), expected)

    def test_snapshot_round_trip_restores_referer_and_clear_resets_it(self):
        source = FitnessSession()
        source.referer_url = "https://tyxylp.xjtu.edu.cn/custom"
        source.headers["X-Fitness-Referer"] = source.referer_url
        source.has_login = True

        restored = FitnessSession()
        restored.restore_site_snapshot(source.to_site_snapshot())
        self.assertEqual(restored.referer_url, source.referer_url)

        restored.clear_site_state()
        self.assertEqual(restored.referer_url, restored.H5_HOME_URL)
        self.assertNotIn("X-Fitness-Referer", restored.headers)


if __name__ == "__main__":
    unittest.main()
