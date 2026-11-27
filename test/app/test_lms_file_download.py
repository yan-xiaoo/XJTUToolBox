import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from requests import ConnectionError, HTTPError

from app.threads.LMSFileDownloadThread import LMSFileDownloadThread


class LMSFileDownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "上课讲义.pdf"
        self.original = b"previous lecture notes"
        self.path.write_bytes(self.original)
        self.session = Mock()
        self.response = self.session.get.return_value
        self.response.headers = {}
        self.worker = LMSFileDownloadThread(self.session, "https://example.invalid/lecture", str(self.path), self.path.name)
        self.finished = Mock()
        self.canceled = Mock()
        self.worker.hasFinished.connect(self.finished)
        self.worker.canceled.connect(self.canceled)

    def assert_existing_file_preserved(self):
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.canceled.assert_called_once_with()
        self.finished.assert_not_called()
        self.response.close.assert_called_once_with()

    def test_http_error_before_writing_preserves_existing_destination(self):
        self.response.raise_for_status.side_effect = HTTPError("503 Service Unavailable")
        self.worker.run()
        self.assert_existing_file_preserved()

    def test_interrupted_stream_preserves_existing_destination(self):
        def chunks():
            yield b"partial replacement"
            raise ConnectionError("connection interrupted")

        self.response.iter_content.return_value = chunks()
        self.worker.run()
        self.assert_existing_file_preserved()

    def test_cancel_at_end_of_stream_preserves_existing_destination(self):
        def chunks():
            yield b"replacement"
            self.worker.onStopSignal()

        self.response.iter_content.return_value = chunks()
        self.worker.run()
        self.assert_existing_file_preserved()

    def test_complete_stream_replaces_existing_destination(self):
        self.response.iter_content.return_value = [b"new ", b"lecture notes"]
        self.worker.run()
        self.assertEqual(self.path.read_bytes(), b"new lecture notes")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.finished.assert_called_once_with()
        self.canceled.assert_not_called()
        self.response.close.assert_called_once_with()
