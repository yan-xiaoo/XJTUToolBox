import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import main_window
from app.main_window import MainWindow


class MainWindowExceptionRoutingTest(unittest.TestCase):
    def _fake_window(self, *, dialog=None):
        return SimpleNamespace(
            unhandledException=Mock(),
            _showUnhandledExceptionDialog=dialog or Mock(),
        )

    def _exc_info(self, exc):
        try:
            raise exc
        except type(exc):
            return sys.exc_info()

    def _run_in_worker(self, callback):
        failures = []

        def runner():
            try:
                callback()
            except BaseException as error:  # pragma: no cover - 失败路径
                failures.append(error)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive(), "worker thread did not finish")
        self.assertEqual(failures, [])

    def test_worker_thread_only_emits_signal_and_builds_no_dialog(self):
        window = self._fake_window()
        exc_info = self._exc_info(ValueError("worker-boom"))

        with (
            patch("app.main_window.MessageBox") as message_box,
            patch("app.main_window.logger"),
            patch("sys.__excepthook__") as fallback,
        ):
            self._run_in_worker(lambda: MainWindow.catchExceptions(window, *exc_info))

        message_box.assert_not_called()
        window._showUnhandledExceptionDialog.assert_not_called()
        window.unhandledException.emit.assert_called_once()
        text = window.unhandledException.emit.call_args.args[0]
        self.assertIn("ValueError", text)
        self.assertIn("worker-boom", text)
        fallback.assert_called_once()

    def test_main_thread_shows_dialog_directly(self):
        dialog = Mock()
        window = self._fake_window(dialog=dialog)
        exc_info = self._exc_info(ValueError("main-boom"))

        with patch("app.main_window.logger"), patch("sys.__excepthook__") as fallback:
            MainWindow.catchExceptions(window, *exc_info)

        dialog.assert_called_once()
        self.assertIn("main-boom", dialog.call_args.args[0])
        window.unhandledException.emit.assert_not_called()
        fallback.assert_called_once()

    def test_threading_hook_logs_with_explicit_traceback(self):
        exc_info = self._exc_info(RuntimeError("thread-boom"))
        hook_args = SimpleNamespace(
            exc_type=exc_info[0],
            exc_value=exc_info[1],
            exc_traceback=exc_info[2],
            thread=threading.current_thread(),
        )

        with patch("app.main_window.logger") as logger:
            main_window._log_uncaught_thread_exception(hook_args)

        logger.error.assert_called_once()
        self.assertEqual(logger.error.call_args.kwargs["exc_info"], exc_info)

    def test_threading_hook_ignores_system_exit(self):
        exc_info = self._exc_info(SystemExit(0))
        hook_args = SimpleNamespace(
            exc_type=exc_info[0],
            exc_value=exc_info[1],
            exc_traceback=exc_info[2],
            thread=threading.current_thread(),
        )
        with patch("app.main_window.logger") as logger:
            main_window._log_uncaught_thread_exception(hook_args)
        logger.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
