import base64
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from auth import ServerError
from auth.constant import FITNESS_LOGIN_URL
from app.sessions.fitness_session import FitnessSession

TEST_DOMAIN = "auth-session"


FITNESS_AES_KEY = b"Wet2C8d34f62ndi3"
FITNESS_AES_IV = b"K6iv85jBD8jgf32D"
FITNESS_SIGN_SALT = "rDJiNB9j7vD2"


def _response(
        url="https://tyxylp.xjtu.edu.cn/callback", *, ok=True, payload=None, error=None, text=""
):
    response = SimpleNamespace(url=url, ok=ok)
    response.json = Mock(side_effect=error) if error else Mock(return_value=payload)
    response.headers = {"Content-Type": "application/json"}
    response.text = text
    return response


def _callback(*, query="", **overrides):
    values = {
        "timestamp": "1700000000",
        "nonce": "123456",
        "course_id": "course-id",
        "uid": "user-id",
        "card_id": "card-id",
        "login_type": "4",
        "type": "1",
        "school_id": "school-id",
        "student_num": "student-id",
        "user_type": "2",
        "token": "session-token",
        "sign": "launch-signature",
        "term_id": "term-id",
    }
    values.update(overrides)
    fragment_query = "&".join(f"{key}={value}" for key, value in values.items())
    query_suffix = f"?{query}" if query else ""
    return (
        "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/"
        f"{query_suffix}#/pages/index/index?{fragment_query}"
    )


def _encrypt_json(payload):
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    cipher = AES.new(FITNESS_AES_KEY, AES.MODE_CBC, FITNESS_AES_IV)
    return base64.b64encode(cipher.encrypt(pad(plaintext, AES.block_size))).decode("ascii")


def _decrypt_json(ciphertext):
    cipher = AES.new(FITNESS_AES_KEY, AES.MODE_CBC, FITNESS_AES_IV)
    plaintext = unpad(cipher.decrypt(base64.b64decode(ciphertext, validate=True)), AES.block_size)
    return json.loads(plaintext.decode("utf-8"))


def _signed_payload(form):
    if set(form) != {"ostype", "data"}:
        raise AssertionError(f"unexpected fitness form keys: {set(form)}")
    if form["ostype"] != 5:
        raise AssertionError(f"unexpected ostype: {form['ostype']!r}")
    payload = _decrypt_json(form["data"])
    signature = payload.pop("sign")
    source = "".join(f"{key}{payload[key]}" for key in sorted(payload)) + FITNESS_SIGN_SALT
    expected_signature = hashlib.md5(source.encode("utf-8")).hexdigest()
    if signature != expected_signature:
        raise AssertionError("fitness request signature does not match the decrypted fields")
    return payload


def _user_info_response(user_info=None):
    if user_info is None:
        user_info = {"uid": "user-id"}
    return _response(payload={
        "status": 1,
        "info": "ok",
        "is_encrypt": 1,
        "data": _encrypt_json(user_info),
    })


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
        session.post = Mock(return_value=_user_info_response())

        with patch("app.sessions.fitness_session.NewLogin", return_value=object()) as login_type:
            session._login("user", "password")
            captured["password_login_factory"]()

        login_type.assert_called_once()
        self.assertEqual(login_type.call_args.args[0], FITNESS_LOGIN_URL)
        self.assertIsNone(captured["qrcode_login_factory"])
        self.assertFalse(captured["allow_qrcode_login"])

    def test_fragment_callback_and_encrypted_user_info_initialize_state(self):
        session = self._session()
        session.perform_cas_login = Mock()
        session.get = Mock(return_value=_response(_callback()))
        session.post = Mock(return_value=_user_info_response())

        with (
            patch("app.sessions.fitness_session.time.time", return_value=1800000000) as now,
            patch("app.sessions.fitness_session.secrets.randbelow", return_value=654321) as nonce,
        ):
            session._login("user", "password")

        self.assertTrue(session.has_login)
        expected_referer = (
            "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/"
            "#/pages/index/index"
        )
        self.assertEqual(session.referer_url, expected_referer)
        self.assertEqual(session.headers["X-Fitness-Referer"], expected_referer)
        session.post.assert_called_once()
        url, kwargs = session.post.call_args
        self.assertEqual(url[0], "https://tyxylp.xjtu.edu.cn/v3/api.php/WpLogin/UserInfo")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(kwargs["headers"]["X-Requested-With"], "XMLHttpRequest")
        self.assertEqual(kwargs["headers"]["Referer"], expected_referer)
        self.assertTrue(kwargs["_skip_auth_check"])
        payload = _signed_payload(kwargs["data"])
        self.assertEqual(
            set(payload),
            {
                "card_id", "class_id", "nonce", "ostype", "role", "school_id",
                "student_num", "term_id", "timestamp", "token", "uid", "version",
            },
        )
        self.assertEqual(payload["uid"], "user-id")
        self.assertEqual(payload["token"], "session-token")
        self.assertEqual(payload["role"], 1)
        self.assertEqual(payload["class_id"], 0)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["ostype"], "5")
        self.assertEqual(payload["nonce"], "654321")
        self.assertEqual(payload["timestamp"], 1800000000)
        now.assert_called_once_with()
        nonce.assert_called_once_with(1_000_000)
        for launch_only in ("course_id", "login_type", "sign", "type", "user_type"):
            self.assertNotIn(launch_only, payload)

    def test_session_fields_come_from_fragment_not_normal_query(self):
        session = self._session()
        session.perform_cas_login = Mock()
        callback = _callback(query="token=query-token&sign=query-sign")
        session.get = Mock(return_value=_response(callback))
        session.post = Mock(return_value=_user_info_response())

        session._login("user", "password")

        payload = _signed_payload(session.post.call_args.kwargs["data"])
        self.assertEqual(payload["token"], "session-token")
        self.assertNotEqual(payload["token"], "query-token")

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

    def test_missing_required_fragment_session_fields_are_rejected(self):
        for missing in (
            "uid", "token", "school_id", "term_id", "student_num", "card_id", "user_type",
        ):
            with self.subTest(missing=missing):
                session = self._session()
                session.perform_cas_login = Mock()
                session.get = Mock(return_value=_response(_callback(
                    query="token=legacy-token&sign=legacy-signature",
                    **{missing: ""},
                )))
                session.post = Mock(return_value=_user_info_response())
                with self.assertRaises(ServerError):
                    session._login("user", "password")
                session.post.assert_not_called()

    def test_unknown_fragment_user_type_is_rejected(self):
        session = self._session()
        session.perform_cas_login = Mock()
        session.get = Mock(return_value=_response(_callback(user_type="99")))
        session.post = Mock(return_value=_user_info_response())

        with self.assertRaises(ServerError):
            session._login("user", "password")

        session.post.assert_not_called()

    def test_user_info_http_envelope_and_decryption_failures(self):
        cases = (
            _response(payload={"status": 0, "info": "denied", "data": ""}),
            _response(ok=False, payload={"status": 1, "data": _encrypt_json({"uid": "user-id"})}),
            _response(payload=["not", "object"]),
            _response(error=ValueError("broken")),
            _response(payload={"status": 1, "data": "not-base64"}),
            _user_info_response({}),
            _response(payload={"status": 1, "data": _encrypt_json(["not", "object"])}),
        )
        for check_response in cases:
            with self.subTest(response=check_response):
                session = self._session()
                session.perform_cas_login = Mock()
                session.get = Mock(return_value=_response(_callback()))
                session.post = Mock(return_value=check_response)
                with self.assertRaises(ServerError):
                    session._login("user", "password")
                self.assertEqual(session._fitness_session, {})
                self.assertNotIn("X-Fitness-Referer", session.headers)

    def test_user_info_network_failure_clears_partial_site_state(self):
        session = self._session()
        session.perform_cas_login = Mock()
        session.get = Mock(return_value=_response(_callback()))
        session.post = Mock(side_effect=requests.ConnectionError("offline"))

        with self.assertRaises(requests.ConnectionError):
            session._login("user", "password")

        self.assertFalse(session.has_login)
        self.assertEqual(session._fitness_session, {})
        self.assertEqual(session.referer_url, session.H5_HOME_URL)
        self.assertNotIn("X-Fitness-Referer", session.headers)

    def test_whole_encrypted_user_info_response_is_accepted(self):
        session = self._session()
        session.perform_cas_login = Mock()
        session.get = Mock(return_value=_response(_callback()))
        ciphertext = _encrypt_json({"uid": "user-id"})
        session.post = Mock(return_value=_response(
            error=ValueError("raw encrypted body is not JSON"),
            text=f"\n{ciphertext}\r\n",
        ))

        session._login("user", "password")

        self.assertTrue(session.has_login)


class FitnessValidationTest(unittest.TestCase):
    def test_validate_login_matrix(self):
        cases = (
            (_user_info_response(), True),
            (_response(payload={"status": 0, "info": "denied", "data": ""}), False),
            (_response(payload=["not", "object"]), False),
            (_response(error=ValueError("broken")), False),
            (_response(payload={"status": 1, "data": "not-base64"}), False),
            (requests.ConnectionError("offline"), False),
        )
        for response_or_error, expected in cases:
            with self.subTest(response=response_or_error):
                session = FitnessSession()
                session._fitness_session = {
                    "card_id": "card-id",
                    "ostype": "5",
                    "role": 1,
                    "school_id": "school-id",
                    "student_num": "student-id",
                    "term_id": "term-id",
                    "token": "session-token",
                    "uid": "user-id",
                }
                if isinstance(response_or_error, Exception):
                    session.post = Mock(side_effect=response_or_error)
                else:
                    session.post = Mock(return_value=response_or_error)
                self.assertIs(session.validate_login(), expected)

    def test_validate_login_rejects_non_ok_and_auth_failure_responses(self):
        non_ok = _response(ok=False, payload={"status": 1, "data": _encrypt_json({"uid": "user-id"})})
        session = FitnessSession()
        session._fitness_session = {"uid": "user-id", "token": "session-token"}
        session.post = Mock(return_value=non_ok)
        self.assertFalse(session.validate_login())

        auth_failed = _user_info_response()
        session = FitnessSession()
        session._fitness_session = {"uid": "user-id", "token": "session-token"}
        session.post = Mock(return_value=auth_failed)
        with patch.object(session, "is_auth_failure_response", return_value=True) as is_auth_failure:
            self.assertFalse(session.validate_login())
        is_auth_failure.assert_called_once_with(auth_failed)

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
        self.assertEqual(restored._fitness_session, {})


if __name__ == "__main__":
    unittest.main()
