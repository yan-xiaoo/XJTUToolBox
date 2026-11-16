import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import requests
from lms import archive_service as archive

TEST_DOMAIN = 'qt-ui'
TEST_REGRESSION = True


class Raw(io.BytesIO):
    def read(self, size=-1, decode_content=True):
        return super().read(size)

    def read1(self, size=-1, decode_content=True):
        return super().read(size)


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kwargs):
        self.calls.append((url, kwargs))
        data, status, headers = self.routes[url]
        response = requests.Response()
        response.status_code, response.url = status, url
        response.headers.update(headers)
        response.raw = Raw(data)
        return response

    def close(self):
        pass


class ExpiringReplaySession(FakeSession):
    """Real replay pipeline with transport-only token expiry injection."""
    def __init__(self, status, always_expired=False):
        super().__init__({})
        self.status, self.always_expired = status, always_expired
        self.details = 0
        self.video = b"v" * 2048

    def request(self, method, url, **kwargs):
        if url == archive.core.BASE + "/api/activities/9?sub_course_id=0":
            self.details += 1
            video_url = "https://video.example.invalid/replay?token=" + str(self.details)
            detail = {"data": {"external_live_detail": {"replay_videos": [
                {"url": video_url, "camera_id": "cam", "camera_type": "encoder"}]}}}
            self.routes[url] = (json.dumps(detail).encode(), 200, {"Content-Type": "application/json"})
        elif kwargs["headers"].get("Range") == "bytes=0-0":
            self.routes[url] = (b"v", 206, {"Content-Range": "bytes 0-0/2048", "ETag": "v1"})
        elif self.always_expired or url.endswith("token=1"):
            self.routes[url] = (b"expired", self.status, {})
        else:
            self.routes[url] = (self.video, 200, {"Content-Length": "2048", "ETag": "v1"})
        return super().request(method, url, **kwargs)


class ArchiveServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'archive'

    def opener(self, routes):
        op = archive.SessionOpener(FakeSession(routes), threading.Event())
        self.addCleanup(op.close)
        return op

    def test_real_collector_discovers_list_body_and_homework_attachments(self):
        base = archive.core.BASE
        payloads = {
            base + '/api/courses/7/activities?sub_course_id=0': {'activities': [
                {'id': 1, 'type': 'material', 'title': '第一章', 'uploads': [{'id': 11}]},
                {'id': 2, 'type': 'page', 'title': '第二章'},
                {'id': 3, 'type': 'homework', 'title': '第三章'}]},
            base + '/api/activities/2?sub_course_id=0': {'data': {'body': '<a href="/api/uploads/12/blob">file</a>'}},
            base + '/api/activities/3?sub_course_id=0': {'data': {'other_resources': [{'id': 13, 'url': ''}]}},
        }
        for uid in (11, 12, 13):
            payloads[base + f'/api/uploads/{uid}'] = {'name': f'{uid}.pdf', 'size': 800}
        op = self.opener({url: (json.dumps(value).encode(), 200, {'Content-Type': 'application/json'})
                          for url, value in payloads.items()})
        items = archive.scan(op, 7)
        self.assertEqual({item['uid'] for item in items}, {11, 12, 13})
        self.assertFalse(self.root.exists(), 'preview must not create files')
        self.assertFalse(any('/blob' in url for url, _ in op.session.calls))

    def item(self, **kwargs):
        return {'kind': '课件', 'activity': '第一章', 'uid': 11, 'name': 'note.txt', 'size': 8, **kwargs}

    def test_small_file_download_uses_core_and_persists_hash_without_secrets(self):
        data = b'12345678'
        op = self.opener({archive.core.BASE + '/api/uploads/11/blob': (data, 200, {'Content-Length': '8'})})
        rows = archive.download(op, 7, [self.item()], self.root)
        self.assertEqual(rows[0]['status'], 'ok')
        self.assertEqual(rows[0]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual((self.root / rows[0]['path']).read_bytes(), data)
        self.assertEqual(json.loads((self.root/'manifest.json').read_text(encoding='utf-8')), rows)
        self.assertNotIn('https:', (self.root/archive.core.INDEX_NAME).read_text(encoding='utf-8'))
        self.assertFalse((self.root/'.toolbox-archive.lock').exists())

    def test_same_named_existing_file_is_preserved(self):
        op = self.opener({archive.core.BASE + '/api/uploads/11/blob': (b'12345678', 200, {})})
        original = self.root/'课件'/'第一章'/'note.txt'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'original')
        rows = archive.download(op, 7, [self.item()], self.root, organize=False)
        self.assertEqual(original.read_bytes(), b'original')
        self.assertNotEqual(self.root/rows[0]['path'], original)

    def test_partial_size_mismatch_never_reports_success(self):
        op = self.opener({archive.core.BASE + '/api/uploads/11/blob': (b'1234', 200, {})})
        with patch.object(archive.core.time, 'sleep'):
            rows = archive.download(op, 7, [self.item()], self.root)
        self.assertEqual(rows[0]['status'], 'failed')
        self.assertFalse((self.root/rows[0]['path']).exists())

    def test_unowned_partial_file_is_preserved(self):
        op = self.opener({archive.core.BASE + '/api/uploads/11/blob': (b'12345678', 200, {})})
        partial = self.root/'课件'/'第一章'/'note.txt.part'
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b'belongs-to-another-download')
        rows = archive.download(op, 7, [self.item()], self.root, organize=False)
        self.assertEqual(rows[0]['status'], 'ok')
        self.assertEqual(partial.read_bytes(), b'belongs-to-another-download')

    def test_stream_cancellation_checked_between_chunks(self):
        op = self.opener({'https://example.invalid/data': (b'12345678', 200, {})})
        response = op.open('https://example.invalid/data')
        self.assertEqual(response.read(4), b'1234')
        op.cancel.set()
        with self.assertRaises(archive.ArchiveStopped):
            response.read(4)

    def test_invalid_range_response_is_rejected(self):
        import urllib.request
        url = archive.core.BASE + '/api/uploads/11/blob'
        op = self.opener({url: (b'wrong', 206, {'Content-Range': 'bytes 0-4/10'})})
        request = urllib.request.Request(url, headers={'Range': 'bytes=5-'})
        with self.assertRaisesRegex(OSError, '范围不匹配'):
            op.open(request)

    def test_resume_uses_validator_and_exact_range(self):
        url = archive.core.BASE + '/api/uploads/11/blob'
        op = self.opener({url: (b'5678', 206, {'Content-Range': 'bytes 4-7/8', 'ETag': '"v1"'})})
        self.root.mkdir()
        path = self.root / 'test.txt'
        Path(str(path) + '.part').write_bytes(b'1234')
        Path(str(path) + '.part.validator').write_text(json.dumps('"v1"'), encoding='utf-8')
        result = archive.core.download(op, 11, str(path), expect_size=8, quiet=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(path.read_bytes(), b'12345678')
        headers = op.session.calls[0][1]['headers']
        self.assertEqual(headers['Range'], 'bytes=4-')
        self.assertEqual(headers['If-range'], '"v1"')

    def test_unidentified_partial_restarts_instead_of_splicing(self):
        url = archive.core.BASE + '/api/uploads/11/blob'
        op = self.opener({url: (b'abcdefgh', 200, {})})
        self.root.mkdir()
        path = self.root / 'test.txt'
        Path(str(path) + '.part').write_bytes(b'1234')
        result = archive.core.download(op, 11, str(path), expect_size=8, quiet=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(path.read_bytes(), b'abcdefgh')
        self.assertNotIn('Range', op.session.calls[0][1]['headers'])

    def test_auth_failure_stops_collector_without_retry(self):
        url = archive.core.BASE + '/api/courses/7/activities?sub_course_id=0'
        op = self.opener({url: (b'', 401, {})})
        with self.assertRaises(archive.ArchiveStopped):
            archive.scan(op, 7)
        self.assertEqual(len(op.session.calls), 1)

    def test_replay_download_uses_real_stability_check_without_persisting_url(self):
        video = b'v' * 2048
        url = 'https://example.invalid/video?token=synthetic-private-token'
        detail = {'data': {'external_live_detail': {'replay_videos': [
            {'url': url, 'camera_id': 'camera1', 'camera_type': 'encoder'}]}}}
        op = self.opener({
            archive.core.BASE + '/api/activities/9?sub_course_id=0':
                (json.dumps(detail).encode(), 200, {'Content-Type': 'application/json'}),
            url: (video, 200, {'Content-Length': str(len(video)), 'ETag': '"v1"'}),
        })
        clock = [0]
        op.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        item = self.item(kind='回放', uid=9, name='replay.mp4', size=len(video), camera_id='camera1', camera='encoder')
        with patch.object(archive.lms_live, 'monotonic', side_effect=lambda: clock[0]):
            rows = archive.download(op, 7, [item], self.root)
        self.assertEqual(rows[0]['status'], 'ok', rows)
        self.assertEqual((self.root/rows[0]['path']).read_bytes(), video)
        self.assertGreaterEqual(clock[0], archive.lms_live.TAIL_STABLE_SECONDS)
        for name in ('manifest.json', archive.core.INDEX_NAME):
            self.assertNotIn('synthetic-private-token', (self.root/name).read_text(encoding='utf-8'))

    def replay_with_expiry(self, status, *, always_expired=False):
        session = ExpiringReplaySession(status, always_expired)
        op = archive.SessionOpener(session, threading.Event())
        self.addCleanup(op.close)
        clock = [0]
        op.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        item = self.item(kind="回放", uid=9, name="replay.mp4", size=2048,
                         camera_id="cam", camera="encoder")
        root = self.root / str(status)
        with patch.object(archive.lms_live, "monotonic", side_effect=lambda: clock[0]):
            rows = archive.download(op, 7, [item], root)
        return session, rows, root

    def test_expired_replay_url_is_refreshed_and_download_verified(self):
        for status in (401, 403):
            with self.subTest(status=status):
                session, rows, root = self.replay_with_expiry(status)
                self.assertEqual(session.details, 2)
                self.assertEqual(rows[0]["status"], "ok", rows)
                self.assertEqual((root / rows[0]["path"]).read_bytes(), session.video)
                self.assertEqual(rows[0]["sha256"], hashlib.sha256(session.video).hexdigest())
                self.assertNotIn("token=", (root / "manifest.json").read_text(encoding="utf-8"))

    def test_replay_url_refresh_has_a_finite_budget(self):
        session, rows, root = self.replay_with_expiry(403, always_expired=True)
        self.assertEqual(session.details, 1 + archive.lms_live.MAX_URL_REFRESHES)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertFalse((root / rows[0]["path"]).exists())
        self.assertFalse((root / ".toolbox-archive.lock").exists())

    def test_webvpn_lms_auth_failure_still_stops_without_retry(self):
        url = archive.core.BASE + "/api/courses/7/activities?sub_course_id=0"
        rewritten = "https://vpn.example.invalid/rewritten"
        session = FakeSession({rewritten: (b"denied", 403, {})})
        op = archive.SessionOpener(session, threading.Event(), rewrite=lambda _: rewritten)
        self.addCleanup(op.close)
        with self.assertRaises(archive.ArchiveStopped):
            archive.scan(op, 7)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], rewritten)

    def test_symlink_target_is_refused(self):
        self.root.mkdir()
        outside = Path(self.temp.name)/'outside.txt'
        outside.write_text('untouched')
        link = self.root/'link.txt'
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest('symlink creation requires Windows privileges')
        with self.assertRaises(ValueError):
            archive.checked_path(self.root, link)
        self.assertEqual(outside.read_text(), 'untouched')

    def test_cancellation_does_not_issue_another_request(self):
        op = self.opener({})
        op.cancel.set()
        with self.assertRaises(archive.ArchiveStopped):
            archive.download(op, 7, [self.item()], self.root)
        self.assertFalse(op.session.calls)
        self.assertFalse((self.root/'.toolbox-archive.lock').exists())

    def test_account_and_course_destinations_are_distinct(self):
        roots = {archive.archive_root(self.temp.name, account, course)
                 for account in ('first', 'second') for course in (1, 2)}
        self.assertEqual(len(roots), 4)
        with self.assertRaises(ValueError):
            archive.checked_path(self.root, self.root/'..'/'escape')

    def test_session_snapshot_preserves_cookie_scope_without_global_auth_headers(self):
        from http.cookiejar import LWPCookieJar
        original = requests.Session()
        self.addCleanup(original.close)
        original.cookies.set('session', 'synthetic', domain='lms.xjtu.edu.cn', path='/', secure=True)
        jar = LWPCookieJar()
        for cookie in original.cookies:
            jar.set_cookie(cookie)
        original.cookies = jar
        original.headers['Authorization'] = 'synthetic-secret'
        copied = archive.snapshot_session(original)
        self.addCleanup(copied.close)
        original.cookies.clear()
        self.assertEqual(len(copied.cookies), 1)
        prepared = copied.prepare_request(requests.Request('GET', 'https://example.invalid/'))
        self.assertNotIn('Cookie', prepared.headers)
        self.assertNotIn('Authorization', prepared.headers)


class ArchiveDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        from app.sub_interfaces.lms.archive_dialog import LMSArchiveDialog
        from app.sessions.session_backend import AccessMode
        session = SimpleNamespace(has_login=True, access_mode=AccessMode.NORMAL)
        account = SimpleNamespace(uuid='synthetic', session_manager=SimpleNamespace(get_session=lambda _: session))
        dialog = LMSArchiveDialog(account, 7, 'Synthetic course')
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_failed_start_unlocks_and_account_change_blocks_actions(self):
        dialog = self.dialog()
        with patch('app.sub_interfaces.lms.archive_dialog.LMSArchiveThread') as thread:
            thread.return_value.start.side_effect = RuntimeError('start failed')
            thread.return_value.isRunning.return_value = False
            dialog.scan()
            self.assertIsNone(dialog.job)
            self.assertTrue(dialog.scanButton.isEnabled())
            self.assertIn('start failed', dialog.status.text())
            dialog.account_changed()
            thread.reset_mock()
            dialog.scan()
            thread.assert_not_called()

    def test_preview_errors_are_visible_and_not_selected(self):
        from PyQt5.QtCore import Qt
        dialog = self.dialog()
        dialog.on_result({'items': [ArchiveServiceTest().item(), ArchiveServiceTest().item(error=True, err_msg='failed detail')]})
        self.assertEqual(dialog.list.item(0).checkState(), Qt.Checked)
        self.assertEqual(dialog.list.item(1).checkState(), Qt.Unchecked)
        self.assertIn('1 项扫描失败', dialog.status.text())

    def test_real_archive_thread_returns_result_and_releases_registry(self):
        import time
        from PyQt5.QtTest import QTest
        from app.threads.LMSArchiveThread import LMSArchiveThread
        session = FakeSession({archive.core.BASE + '/api/courses/7/activities?sub_course_id=0':
                               (b'{"activities": []}', 200, {'Content-Type': 'application/json'})})
        with patch.object(archive, 'snapshot_session', return_value=session):
            thread = LMSArchiveThread(object(), 7)
        results = []
        thread.result.connect(results.append)
        thread.start()
        deadline = time.monotonic() + 5
        while thread.isRunning() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(thread.wait(1000))
        self.app.processEvents()
        self.assertEqual(results, [{'ok': True, 'items': []}])
        self.assertNotIn(thread, thread._active_jobs)
        thread.deleteLater()
