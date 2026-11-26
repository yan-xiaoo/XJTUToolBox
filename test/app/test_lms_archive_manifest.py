import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.threads.LMSBatchDownloadThread import LMSBatchDownloadThread, _DownloadJob, _WorkerThread
from lms.archive_manifest import ArchiveManifest


class Response:
    def __init__(self, data=b"sample content", error=False, on_chunk=None):
        self.data, self.error, self.on_chunk = data, error, on_chunk
        self.headers = {"Content-Length": str(len(data))}
        self.closed = False

    def raise_for_status(self):
        if self.error:
            raise OSError("synthetic download failure")

    def iter_content(self, chunk_size):
        if self.on_chunk:
            self.on_chunk()
        yield self.data

    def close(self):
        self.closed = True


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def worker(self, response):
        path = self.root / "file.txt"
        session = SimpleNamespace(get=Mock(return_value=response))
        worker = _WorkerThread(_DownloadJob("https://example.invalid/file?token=secret", str(path), "file", session))
        return worker, path

    def test_worker_success_has_digest_and_atomic_result(self):
        response = Response()
        worker, path = self.worker(response)
        worker.run()
        self.assertTrue(worker.success)
        self.assertEqual(path.read_bytes(), response.data)
        self.assertEqual(worker.sha256, hashlib.sha256(response.data).hexdigest())
        self.assertTrue(response.closed)
        self.assertEqual(list(self.root.glob(".lms-download-*")), [])

    def test_network_failure_preserves_existing_file(self):
        worker, path = self.worker(Response(error=True))
        path.write_bytes(b"previous download")
        worker.run()
        self.assertFalse(worker.success)
        self.assertEqual(path.read_bytes(), b"previous download")

    def test_cancel_removes_only_temporary_file_after_close(self):
        response = Response()
        worker, path = self.worker(response)
        path.write_bytes(b"previous download")
        response.on_chunk = worker.stop
        worker.run()
        self.assertFalse(worker.success)
        self.assertEqual(path.read_bytes(), b"previous download")
        self.assertEqual(list(self.root.glob(".lms-download-*")), [])
        self.assertTrue(response.closed)

    def test_short_response_is_failure(self):
        response = Response()
        response.headers["Content-Length"] = "900"
        worker, path = self.worker(response)
        worker.run()
        self.assertFalse(worker.success)
        self.assertFalse(path.exists())

    def test_encoded_response_length_is_not_decoded_file_length(self):
        response = Response()
        response.headers.update({"Content-Length": "900", "Content-Encoding": "gzip"})
        worker, _ = self.worker(response)
        worker.run()
        self.assertTrue(worker.success)

    def batch(self, *, archive=True, error=False):
        activities = [{"id": 1, "title": "活动", "type": "material", "download_url": "secret"}]
        batch = LMSBatchDownloadThread(activities, "material", None, str(self.root), "flat",
                                       archive=archive, course_name="课程")
        batch._session = SimpleNamespace(get=lambda *a, **k: Response(error=error))
        batch._ensure_login = lambda: True
        batch._collect_all = lambda: [("https://example.invalid/?secret=1", "same.txt", "A", "activity"),
                                      ("https://example.invalid/?secret=2", "SAME.TXT", "B", "activity")]
        return batch

    def test_archive_reuses_downloader_and_counts_before_completion(self):
        batch = self.batch()
        totals = []
        batch.allCompleted.connect(lambda ok, fail: totals.append((ok, fail)))
        batch.run()
        self.assertEqual(totals, [(2, 0)])
        manifest = json.loads(batch._archive.path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(len({r["path"].casefold() for r in manifest["files"]}), 2)
        for row in manifest["files"]:
            content = (batch._archive.root / row["path"]).read_bytes()
            self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(row["size"], len(content))
        text = batch._archive.path.read_text(encoding="utf-8")
        self.assertNotIn("secret", text)
        self.assertNotIn("https://", text)

    def test_failed_download_is_recorded_as_partial(self):
        batch = self.batch(error=True)
        batch.run()
        data = batch._archive.data
        self.assertEqual(data["status"], "partial")
        self.assertTrue(all(r["status"] == "failed" for r in data["files"]))
        self.assertEqual(batch._fail_count, 2)

    def test_disabled_option_creates_no_manifest(self):
        batch = self.batch(archive=False)
        batch.run()
        self.assertIsNone(batch._archive)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_cancel_sets_coordinator_flag_and_marks_pending(self):
        batch = self.batch()
        batch._session.get = lambda *a, **k: Response(on_chunk=batch.onStopSignal)
        batch.max_concurrent = lambda: 1
        batch.run()
        self.assertFalse(batch.can_run)
        self.assertEqual(batch._archive.data["status"], "cancelled")
        self.assertTrue(all(r["status"] == "cancelled" for r in batch._archive.data["files"]))
        self.assertEqual(batch._active_workers, [])

    def test_collection_failure_is_not_reported_as_complete(self):
        batch = self.batch()
        batch._collect_all = lambda: LMSBatchDownloadThread._collect_all(batch)
        batch._util = SimpleNamespace(get_activity_detail=Mock(side_effect=OSError("unavailable")))
        batch.run()
        self.assertEqual(batch._archive.data["status"], "partial")
        self.assertEqual(batch._archive.data["collection_failures"][0]["id"], 1)

    def test_archive_option_only_uses_existing_activity_api(self):
        batch = self.batch()
        batch._collect_all = lambda: LMSBatchDownloadThread._collect_all(batch)
        detail = {"uploads": [{"name": "note.txt", "download_url": "https://example.invalid/note"}]}
        batch._util = SimpleNamespace(get_activity_detail=Mock(return_value=detail))
        batch.run()
        batch._util.get_activity_detail.assert_called_once_with(1)
        self.assertEqual(batch._success_count, 1)

    def test_manifest_runs_do_not_overwrite_earlier_archive(self):
        first = ArchiveManifest(self.root, "课程", [])
        second = ArchiveManifest(self.root, "课程", [])
        self.assertNotEqual(first.root, second.root)
        self.assertTrue(first.path.exists())

    def test_path_components_cannot_escape_output_folder(self):
        for name in ("../outside", "a/b\\c", "CON", "NUL.txt", "..."):
            cleaned = LMSBatchDownloadThread._sanitize_filename(name)
            self.assertNotIn("/", cleaned)
            self.assertNotIn("\\", cleaned)
            self.assertNotIn(cleaned.upper(), ("CON", "NUL.TXT", ".."))

    def test_worker_start_failure_drains_already_started_workers(self):
        batch = self.batch()
        original = _WorkerThread.start
        started = []
        def start(worker):
            if started:
                raise RuntimeError("synthetic thread start failure")
            started.append(worker)
            original(worker)
        with patch.object(_WorkerThread, "start", start):
            batch.run()
        self.assertEqual(batch._active_workers, [])
        self.assertTrue(all(not worker.isRunning() for worker in started))
        self.assertEqual(batch._archive.data["status"], "failed")

    def test_marked_attachment_failure_is_recorded(self):
        failures = []
        util = SimpleNamespace(get_submission_marked_attachments=Mock(side_effect=OSError("unavailable")))
        LMSBatchDownloadThread._collect_marked_attachments([], {"submission_list": {"list": [{"id": 12}]}},
                                                           "title", "title", util, failures)
        self.assertEqual(failures, [{"submission_id": 12, "reason": "marked_attachments_unavailable"}])

    def test_filename_control_characters_are_removed(self):
        for control in range(32):
            cleaned = LMSBatchDownloadThread._sanitize_filename("before" + chr(control) + "after.pdf")
            self.assertFalse(any(ord(c) < 32 for c in cleaned))
            self.assertTrue(cleaned.endswith(".pdf"))

    def test_plain_batch_keeps_long_filename_extension_and_duplicate_suffix(self):
        batch = self.batch(archive=False)
        name = "a" * 160 + ".pdf"
        batch._collect_all = lambda: [
            ("https://example.invalid/one", name, "A", "activity"),
            ("https://example.invalid/two", name, "B", "activity"),
        ]
        batch.run()
        self.assertEqual(batch._success_count, 2)
        self.assertEqual({path.name for path in self.root.iterdir()}, {
            "a" * 156 + ".pdf",
            "a" * 154 + "_2.pdf",
        })

    def test_plain_batch_fits_multibyte_duplicate_in_directory_byte_limit(self):
        batch = self.batch(archive=False)
        name = "课" * 83 + "ab.pdf"
        self.assertEqual(len(os.fsencode(name)), 255)
        batch._collect_all = lambda: [
            ("https://example.invalid/one", name, "A", "activity"),
            ("https://example.invalid/two", name, "B", "activity"),
        ]
        with patch.object(os, "pathconf", return_value=255, create=True) as pathconf:
            batch.run()

        pathconf.assert_called_with(str(self.root), "PC_NAME_MAX")
        self.assertEqual((batch._success_count, batch._fail_count), (2, 0))
        self.assertEqual({path.name for path in self.root.iterdir()}, {
            name,
            "课" * 83 + "_2.pdf",
        })

    def test_missing_attachment_url_is_partial_not_complete(self):
        batch = self.batch()
        batch._collect_all = lambda: LMSBatchDownloadThread._collect_all(batch)
        batch._util = SimpleNamespace(get_activity_detail=lambda _: {"uploads": [{"name": "missing.pdf"}]})
        batch.run()
        self.assertEqual(batch._archive.data["status"], "partial")
        self.assertEqual(batch._archive.data["files"], [])
        self.assertEqual(batch._archive.data["collection_failures"], [
            {"id": 1, "source": "uploads", "reason": "missing_download_url"}])

    def test_all_attachment_sources_record_missing_urls(self):
        cases = [
            (LMSBatchDownloadThread._collect_uploads, {"uploads": [{"name": "x"}]}, ()),
            (LMSBatchDownloadThread._collect_submission_uploads,
             {"submission_list": {"uploads": [{"name": "x"}], "list": [{"uploads": [{"name": "y"}]}]}}, ()),
            (LMSBatchDownloadThread._collect_replay_videos, {"replay_videos": [{"label": "x"}]}, ()),
            (LMSBatchDownloadThread._collect_marked_attachments,
             {"submission_list": {"list": [{"id": 3}]}},
             (SimpleNamespace(get_submission_marked_attachments=lambda _: {"rules": [{"origin_upload_name": "x"}]}),)),
        ]
        for collect, detail, extra in cases:
            with self.subTest(source=collect.__name__):
                files, failures = [], []
                collect(files, detail, "activity", "activity", *extra, failures=failures)
                self.assertEqual(files, [])
                self.assertTrue(failures)
                self.assertTrue(all(f["reason"] == "missing_download_url" for f in failures))

    def test_malformed_attachment_lists_are_recorded(self):
        for value in ({"unexpected": "shape"}, [None, 7, "bad"]):
            with self.subTest(value=value):
                files, failures = [], []
                LMSBatchDownloadThread._collect_uploads(files, {"uploads": value}, "a", "a", failures)
                self.assertEqual(files, [])
                self.assertTrue(failures)

    def test_fallback_url_is_used_without_false_failure(self):
        files, failures = [], []
        LMSBatchDownloadThread._collect_uploads(files, {"uploads": [
            {"download_url": 123, "preview_url": "https://example.invalid/ok", "name": "x"}]}, "a", "a", failures)
        self.assertEqual(len(files), 1)
        self.assertEqual(failures, [])

    def test_genuinely_empty_activity_is_complete(self):
        batch = self.batch()
        batch._collect_all = lambda: LMSBatchDownloadThread._collect_all(batch)
        batch._util = SimpleNamespace(get_activity_detail=lambda _: {"uploads": []})
        batch.run()
        self.assertEqual(batch._archive.data["status"], "complete")
        self.assertEqual(batch._archive.data["collection_failures"], [])

    def test_mixed_missing_and_downloaded_attachments_remain_partial(self):
        batch = self.batch()
        batch._collect_all = lambda: LMSBatchDownloadThread._collect_all(batch)
        batch._util = SimpleNamespace(get_activity_detail=lambda _: {"uploads": [
            {"name": "missing"}, {"name": "ok", "download_url": "https://example.invalid/ok"}]})
        batch.run()
        self.assertEqual(batch._success_count, 1)
        self.assertEqual(batch._archive.data["status"], "partial")
        self.assertEqual(len(batch._archive.data["collection_failures"]), 1)

    def test_gui_watchdog_waits_for_cancelled_archive_cleanup(self):
        from PyQt5.QtWidgets import QApplication
        from qfluentwidgets import InfoBarPosition
        from app.components.ProgressInfoBar import ProgressInfoBar
        app = QApplication.instance() or QApplication([])
        entered, release = threading.Event(), threading.Event()
        batch = self.batch()
        batch.max_concurrent = lambda: 1
        def get(*args, **kwargs):
            entered.set()
            release.wait(5)
            return Response()
        batch._session.get = get
        bar = ProgressInfoBar("test", "test", position=InfoBarPosition.NONE)
        bar.connectToThread(batch)
        batch.start()
        try:
            self.assertTrue(entered.wait(2))
            app.processEvents()
            bar.onCloseButtonClicked()
            bar.dead_time_start = time.time() - 10
            with patch.object(batch, "terminate") as terminate:
                bar.checkProcess()
                terminate.assert_not_called()
            self.assertTrue(batch.isRunning())
        finally:
            release.set()
            batch.wait(5000)
        self.assertFalse(batch.isRunning())
        data = json.loads(batch._archive.path.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "cancelled")
        self.assertTrue(all(row["status"] == "cancelled" for row in data["files"]))
        self.assertEqual(batch._active_workers, [])
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
