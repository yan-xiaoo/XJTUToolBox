import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from auth import ServerError
from auth.constant import HELLO_LOGIN_URL
from app.sessions.hello_session import (
    HelloLogin,
    HelloSession,
    HelloTokenMixin,
    HelloWebVPNLogin,
    _jwt_system_type,
    extract_hello_token,
)
from app.sessions.session_backend import AccessMode, SessionBackend


DEFAULT_SYSTEM_TYPE = "yingxin_student_pc"


def _jwt(payload, *, keep_padding=False):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode()
    if not keep_padding:
        encoded = encoded.rstrip("=")
    return f"header.{encoded}.signature"


def _response(url="", *, request_url="", history=()):
    request = SimpleNamespace(url=request_url) if request_url else None
    return SimpleNamespace(url=url, request=request, history=list(history))


class _LoginProbe(HelloTokenMixin):
    def __init__(self, session):
        self.session = session


class HelloTokenExtractionTest(unittest.TestCase):
    def test_final_response_url_supplies_token(self):
        token = _jwt({"systemType": "student"})
        response = _response(f"https://hello.xjtu.edu.cn/callback?token={token}")
        self.assertEqual(extract_hello_token(response), token)

    def test_original_request_url_supplies_token(self):
        token = _jwt({"systemType": "student"})
        response = _response(
            "https://login.xjtu.edu.cn/complete",
            request_url=f"https://hello.xjtu.edu.cn/callback?token={token}",
        )
        self.assertEqual(extract_hello_token(response), token)

    def test_redirect_history_supplies_token(self):
        token = _jwt({"systemType": "teacher"})
        history = [_response(f"https://hello.xjtu.edu.cn/callback?token={token}")]
        response = _response("https://login.xjtu.edu.cn/complete", history=history)
        self.assertEqual(extract_hello_token(response), token)

    def test_trusted_hello_candidate_beats_untrusted_candidate(self):
        untrusted = _jwt({"systemType": "evil"})
        trusted = _jwt({"systemType": "trusted"})
        response = _response(
            f"https://example.com/callback?token={untrusted}",
            history=[_response(f"https://hello.xjtu.edu.cn/callback?token={trusted}")],
        )
        self.assertEqual(extract_hello_token(response), trusted)

    def test_webvpn_encrypted_hello_url_is_trusted(self):
        token = _jwt({"systemType": "webvpn"})
        encrypted = f"https://webvpn.xjtu.edu.cn/http/opaque/path?token={token}"
        with patch(
            "app.sessions.hello_session.getOrdinaryUrl",
            return_value=f"http://hello.xjtu.edu.cn/callback?token={token}",
        ):
            self.assertEqual(extract_hello_token(_response(encrypted)), token)

    def test_untrusted_host_and_spoofed_suffix_are_rejected(self):
        token = _jwt({"systemType": "evil"})
        for url in (
            f"https://example.com/callback?token={token}",
            f"https://hello.xjtu.edu.cn.evil.com/callback?token={token}",
            f"https://evil.com/callback?next={token}",
        ):
            with self.subTest(url=url):
                self.assertEqual(extract_hello_token(_response(url)), "")


class HelloJwtAndSessionTest(unittest.TestCase):
    def test_jwt_payload_with_and_without_padding(self):
        self.assertEqual(_jwt_system_type(_jwt({"systemType": "student"})), "student")
        self.assertEqual(
            _jwt_system_type(_jwt({"systemType": "teacher"}, keep_padding=True)),
            "teacher",
        )

    def test_bad_or_non_object_jwt_payload_uses_default(self):
        non_object = _jwt(["not", "an", "object"])
        for token in ("", "one-part", "header.%%%.signature", non_object):
            with self.subTest(token=token):
                self.assertEqual(_jwt_system_type(token), DEFAULT_SYSTEM_TYPE)

    def test_post_login_stores_both_headers_and_system_type(self):
        session = HelloSession()
        token = _jwt({"systemType": "teacher_pc"})
        _LoginProbe(session).postLogin(
            _response(f"https://hello.xjtu.edu.cn/callback?token={token}")
        )
        self.assertEqual(session.access_token, token)
        self.assertEqual(session.system_type, "teacher_pc")
        self.assertEqual(session.headers["access-token"], token)
        self.assertEqual(session.headers["access_token"], token)
        self.assertEqual(session.headers["systemtype"], "teacher_pc")

    def test_post_login_replays_oauth_entry_after_code_only_cas_response(self):
        session = HelloSession()
        token = _jwt({"systemType": "student_pc"})
        probe = _LoginProbe(session)
        probe._get = Mock(
            return_value=_response(
                "http://hello.xjtu.edu.cn/yingxin-pc/index?uuid=redacted",
                history=[_response(
                    f"http://hello.xjtu.edu.cn/yingxin-pc/?token={token}&uuid=redacted"
                )],
            )
        )

        probe.postLogin(
            _response(
                "https://org.xjtu.edu.cn/openplatform/oauth/authorizesw"
                "?code=redacted&state=pc"
            )
        )

        probe._get.assert_called_once_with(HELLO_LOGIN_URL, allow_redirects=True)
        self.assertEqual(session.access_token, token)
        self.assertEqual(session.headers["access-token"], token)

    def test_post_login_without_token_after_replay_raises_server_error(self):
        probe = _LoginProbe(HelloSession())
        probe._get = Mock(
            return_value=_response(
                "http://hello.xjtu.edu.cn/yingxin/login/xjtu/oauth/pc"
                "?code=redacted&state=pc"
            )
        )

        with self.assertRaises(ServerError):
            probe.postLogin(_response("https://hello.xjtu.edu.cn/"))

        probe._get.assert_called_once_with(HELLO_LOGIN_URL, allow_redirects=True)

    def test_clear_site_state_removes_all_site_authentication_state(self):
        session = HelloSession()
        session.access_token = "secret"
        session.system_type = "teacher_pc"
        session.has_login = True
        session._store_tokens()

        session.clear_site_state()

        self.assertFalse(session.has_login)
        self.assertEqual(session.access_token, "")
        self.assertEqual(session.system_type, DEFAULT_SYSTEM_TYPE)
        for header in ("access-token", "access_token", "systemtype", "synAccessSource"):
            self.assertNotIn(header, session.headers)

    def test_site_snapshot_restores_token_headers_and_system_type(self):
        source = HelloSession()
        source.access_token = "saved-token"
        source.system_type = "teacher_pc"
        source._store_tokens()
        source.has_login = True

        restored = HelloSession()
        restored.restore_site_snapshot(source.to_site_snapshot())

        self.assertTrue(restored.has_login)
        self.assertEqual(restored.access_token, "saved-token")
        self.assertEqual(restored.system_type, "teacher_pc")
        self.assertEqual(restored.headers["access-token"], "saved-token")
        self.assertEqual(restored.headers["access_token"], "saved-token")

    def test_access_mode_selects_matching_login_adapter(self):
        for mode, expected_factory in (
            (AccessMode.NORMAL, "normal"),
            (AccessMode.WEBVPN, "webvpn"),
        ):
            with self.subTest(mode=mode):
                session = HelloSession(backend=SessionBackend(mode))
                adapters = []

                def perform_cas_login(*_args, **kwargs):
                    adapters.append(kwargs["password_login_factory"]())
                    self.assertIsNone(kwargs["qrcode_login_factory"])
                    self.assertFalse(kwargs["allow_qrcode_login"])
                    session.access_token = "opaque-token"
                    session._store_tokens()

                session.perform_cas_login = perform_cas_login
                with (
                    patch("app.sessions.hello_session.HelloLogin", return_value="normal") as normal,
                    patch("app.sessions.hello_session.HelloWebVPNLogin", return_value="webvpn") as webvpn,
                ):
                    session._login("user", "password")
                self.assertEqual(adapters, [expected_factory])
                selected = normal if mode == AccessMode.NORMAL else webvpn
                unselected = webvpn if mode == AccessMode.NORMAL else normal
                selected.assert_called_once_with(session=session, visitor_id=unittest.mock.ANY)
                unselected.assert_not_called()

    def test_validate_login_response_matrix(self):
        cases = (
            (SimpleNamespace(json=lambda: {"state": 200}), True),
            (SimpleNamespace(json=lambda: {"state": 401}), False),
            (SimpleNamespace(json=lambda: ["not", "object"]), False),
            (SimpleNamespace(json=Mock(side_effect=ValueError("broken"))), False),
            (requests.ConnectionError("offline"), False),
        )
        for response_or_error, expected in cases:
            with self.subTest(response=response_or_error):
                session = HelloSession()
                session.access_token = "token"
                if isinstance(response_or_error, Exception):
                    session.get = Mock(side_effect=response_or_error)
                else:
                    session.get = Mock(return_value=response_or_error)
                self.assertIs(session.validate_login(), expected)
                self.assertEqual(session.headers["access-token"], "token")

    def test_validate_login_without_token_does_not_request(self):
        session = HelloSession()
        session.get = Mock()
        self.assertFalse(session.validate_login())
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
