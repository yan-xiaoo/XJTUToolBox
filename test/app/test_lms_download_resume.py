import gzip
import hashlib
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from unittest.mock import Mock, patch

import requests

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.threads.LMSFileDownloadThread import LMSFileDownloadThread
from app.threads.lms_download_resume import PartialDownload, download_identity


class LMSDownloadResumeTest(unittest.TestCase):
    prefix = b"A" * 16384
    payload = prefix + b"B" * 8192
    original = b"existing file"
    etag = '"original-version"'

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "课件.mp4"
        self.path.write_bytes(self.original)
        self.session = requests.Session()
        self.session.trust_env = False
        self.addCleanup(self.session.close)
        self.responses = Queue()
        self.requests = []
        responses, seen = self.responses, self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers)
                try:
                    status, headers, data = responses.get_nowait()
                except Empty:
                    self.send_error(500, "Unexpected extra request")
                    return
                self.send_response(status)
                self.send_header("Connection", "close")
                for name, value in headers.items():
                    self.send_header(name, str(value))
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        server_thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server_thread.join, 2)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}/replay.mp4"

    def queue_response(self, status, data, *, etag=etag, length=None, **headers):
        headers["Content-Length"] = len(data) if length is None else length
        if etag is not None:
            headers["ETag"] = etag
        self.responses.put((status, headers, data))

    def make_worker(self, **kwargs):
        url = kwargs.pop("url", self.url)
        worker = LMSFileDownloadThread(self.session, url, str(self.path), self.path.name, **kwargs)
        done, error, canceled = Mock(), Mock(), Mock()
        worker.hasFinished.connect(done)
        worker.error.connect(error)
        worker.canceled.connect(canceled)
        return worker, done, error, canceled

    def interrupt(self, **kwargs):
        self.queue_response(200, self.prefix, length=len(self.payload))
        worker, done, error, canceled = self.make_worker(**kwargs)
        worker.run()
        done.assert_not_called()
        error.assert_called_once()
        canceled.assert_called_once()
        self.assertEqual(self.path.read_bytes(), self.original)

    def assert_saved(self, payload, done, error, canceled):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), hashlib.sha256(payload).digest())
        done.assert_called_once()
        error.assert_not_called()
        canceled.assert_not_called()
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_interrupted_download_resumes_from_the_saved_byte_offset(self):
        self.interrupt()
        parts = list(self.path.parent.rglob("*.part"))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].read_bytes(), self.prefix)

        start = len(self.prefix)
        self.queue_response(
            206, self.payload[start:],
            **{"Content-Range": f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}"},
        )
        worker, done, error, canceled = self.make_worker()
        worker.run()

        self.assertIsNone(self.requests[0].get("Range"))
        self.assertEqual(self.requests[1]["Range"], f"bytes={start}-")
        self.assertEqual(self.requests[1]["If-Range"], self.etag)
        self.assertEqual(self.requests[1]["Accept-Encoding"], "identity")
        self.assert_saved(self.payload, done, error, canceled)

    def test_full_response_replaces_the_old_prefix_instead_of_appending(self):
        self.interrupt()
        replacement = b"the entire new version"
        self.queue_response(200, replacement, etag='"new-version"')
        worker, done, error, canceled = self.make_worker()
        worker.run()

        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[-1]["Range"], f"bytes={len(self.prefix)}-")
        self.assert_saved(replacement, done, error, canceled)

    def test_rejected_range_is_retried_with_a_full_request(self):
        start = len(self.prefix)
        total = len(self.payload)
        remaining = self.payload[start:]
        for status, etag, headers, data in [
            (416, self.etag, {"Content-Range": f"bytes */{total}"}, b""),
            (200, self.etag, {"Content-Range": f"bytes {start}-{total - 1}/{total}"}, remaining),
            (206, self.etag, {"Content-Range": f"bytes {start - 1}-{total - 1}/{total}"}, remaining),
            (206, self.etag, {"Content-Range": f"bytes {start}-{total - 2}/{total}"}, remaining[:-1]),
            (206, self.etag, {"Content-Range": f"bytes {start}-{total}/{total + 1}"}, remaining + b"C"),
            (206, '"changed"', {"Content-Range": f"bytes {start}-{total - 1}/{total}"}, remaining),
            (206, self.etag, {"Content-Range": f"bytes {start}-{total - 1}/{total}",
                               "Content-Encoding": "gzip"}, gzip.compress(remaining)),
        ]:
            with self.subTest(status=status, etag=etag, headers=headers):
                self.path.write_bytes(self.original)
                self.interrupt()
                self.queue_response(status, data, etag=etag, **headers)
                self.queue_response(200, self.payload)
                worker, done, error, canceled = self.make_worker()
                worker.run()

                self.assertEqual(self.requests[-2]["Range"], f"bytes={start}-")
                self.assertIsNone(self.requests[-1].get("Range"))
                self.assert_saved(self.payload, done, error, canceled)

    def test_same_entity_with_conflicting_length_does_not_replace_existing_file(self):
        self.interrupt()
        self.queue_response(200, b"short response")
        worker, done, error, canceled = self.make_worker()
        worker.run()

        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.requests[-1]["Range"], f"bytes={len(self.prefix)}-")
        done.assert_not_called()
        error.assert_called_once()
        canceled.assert_called_once()

    def test_second_interruption_updates_the_checkpoint(self):
        payload = self.prefix + b"B" * 8192 + b"C" * 8192
        start, end = len(self.prefix), len(payload) - 1
        self.queue_response(200, self.prefix, length=len(payload))
        worker, done, error, canceled = self.make_worker()
        worker.run()
        error.assert_called_once()

        self.queue_response(206, payload[start:start + 8192], length=len(payload) - start,
                            **{"Content-Range": f"bytes {start}-{end}/{len(payload)}"})
        worker, done, error, canceled = self.make_worker()
        worker.run()
        self.assertEqual(self.path.read_bytes(), self.original)
        error.assert_called_once()

        next_start = start + 8192
        self.queue_response(206, payload[next_start:], **{"Content-Range": f"bytes {next_start}-{end}/{len(payload)}"})
        worker, done, error, canceled = self.make_worker()
        worker.run()
        self.assertEqual([request.get("Range") for request in self.requests],
                         [None, f"bytes={start}-", f"bytes={next_start}-"])
        self.assert_saved(payload, done, error, canceled)

    def test_weak_validator_leaves_no_partial_download(self):
        self.queue_response(200, self.prefix, etag='W/"weak"', length=len(self.payload))
        worker, done, error, canceled = self.make_worker()
        worker.run()

        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        done.assert_not_called()
        error.assert_called_once()
        canceled.assert_called_once()

        self.queue_response(200, self.payload, etag=None)
        worker, done, error, canceled = self.make_worker()
        worker.run()
        self.assertIsNone(self.requests[-1].get("Range"))
        self.assert_saved(self.payload, done, error, canceled)

    def test_valid_range_can_resume_after_the_replay_signature_is_refreshed(self):
        identity = {"replay_file_key": "replay-file-4", "account_id": "test-account"}
        self.interrupt(url=f"{self.url}?signature=first", **identity)
        start = len(self.prefix)
        self.queue_response(
            206, self.payload[start:],
            **{"Content-Range": f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}"},
        )
        worker, done, error, canceled = self.make_worker(url=f"{self.url}?signature=second", **identity)
        worker.run()

        self.assertEqual(self.requests[-1]["Range"], f"bytes={start}-")
        self.assert_saved(self.payload, done, error, canceled)

    def test_other_account_cannot_reuse_the_existing_prefix(self):
        self.interrupt(account_id="first-account")
        self.queue_response(200, self.payload)
        worker, done, error, canceled = self.make_worker(account_id="second-account")
        worker.run()

        self.assertIsNone(self.requests[-1].get("Range"))
        self.assert_saved(self.payload, done, error, canceled)

    def test_disk_error_before_replace_preserves_the_original(self):
        self.queue_response(200, self.payload)
        worker, done, error, canceled = self.make_worker()
        with patch("app.threads.LMSFileDownloadThread.os.fsync", side_effect=OSError("disk full")):
            worker.run()

        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        done.assert_not_called()
        error.assert_called_once()
        canceled.assert_called_once()

    def test_unowned_staging_directory_is_left_alone(self):
        partial = PartialDownload(self.path.resolve(), download_identity(self.url))
        partial.directory.mkdir()
        partial.data_path.write_bytes(b"user file")
        self.queue_response(200, self.payload)
        worker, done, error, canceled = self.make_worker()
        worker.run()

        self.assertEqual(self.path.read_bytes(), self.payload)
        self.assertEqual(partial.data_path.read_bytes(), b"user file")
        done.assert_called_once()
        error.assert_not_called()
        canceled.assert_not_called()

    def test_cancel_after_the_last_chunk_keeps_the_original_and_clears_checkpoint(self):
        self.queue_response(200, self.payload)
        worker, done, error, canceled = self.make_worker()
        worker.progressChanged.connect(lambda value: worker.onStopSignal() if value == 100 else None)
        worker.run()

        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        done.assert_not_called()
        error.assert_not_called()
        canceled.assert_called_once()

    def test_same_destination_cannot_be_downloaded_twice_concurrently(self):
        self.queue_response(200, self.payload)
        worker, done, error, canceled = self.make_worker()
        duplicate, duplicate_done, duplicate_error, duplicate_canceled = self.make_worker()

        def start_duplicate(value):
            if value == 0:
                return
            worker.progressChanged.disconnect(start_duplicate)
            duplicate.run()

        worker.progressChanged.connect(start_duplicate)
        worker.run()

        self.assertEqual(len(self.requests), 1)
        duplicate_done.assert_not_called()
        duplicate_error.assert_called_once()
        duplicate_canceled.assert_called_once()
        self.assert_saved(self.payload, done, error, canceled)
