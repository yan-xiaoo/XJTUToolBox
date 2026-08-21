import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from auth import ServerError
from app.threads.CampusFeatureThread import CampusFeatureThread
from app.utils.mfa import MFACancelledError, MFAUnavailableError
from app.utils.qrcode_login import QRCodeLoginCancelledError, QRCodeLoginUnavailableError
from app.utils.campus_job import JOB_FAILED, run_campus_job


def _thread():
    thread = SimpleNamespace(can_run=True)
    thread.tr = lambda text: text
    thread.error = Mock()
    thread.canceled = Mock()
    thread.setIndeterminate = Mock()
    thread.messageChanged = Mock()
    return thread


class CampusJobTest(unittest.TestCase):
    def test_missing_account_is_failure_not_none(self):
        thread = _thread()
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = None
            result = run_campus_job(
                thread,
                site_key="hello",
                login_message="login",
                worker=lambda session: None,
            )
        self.assertIs(result, JOB_FAILED)
        self.assertFalse(thread.can_run)
        thread.canceled.emit.assert_called_once()

    def test_worker_none_is_success(self):
        account = SimpleNamespace(
            username="u",
            password="p",
            session_manager=SimpleNamespace(
                get_session=lambda key: SimpleNamespace(
                    ensure_login=lambda *args, **kwargs: None,
                ),
                mfa_provider=None,
            ),
        )
        thread = _thread()
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = account
            result = run_campus_job(
                thread,
                site_key="library",
                login_message="login",
                worker=lambda session: None,
            )
        self.assertIsNone(result)
        self.assertTrue(thread.can_run)

    def test_uses_account_snapshot_after_switch(self):
        session = SimpleNamespace(seen=None)

        def ensure_login(username, password, account=None, mfa_provider=None):
            session.seen = (username, password, account)

        first = SimpleNamespace(
            username="a",
            password="ap",
            session_manager=SimpleNamespace(
                get_session=lambda key: SimpleNamespace(ensure_login=ensure_login),
                mfa_provider="mfa-a",
            ),
        )
        second = SimpleNamespace(username="b", password="bp")
        holder = SimpleNamespace(current=first)
        thread = _thread()

        def worker(_session):
            holder.current = second
            return "ok"

        with patch("app.utils.campus_job.accounts", holder):
            result = run_campus_job(
                thread,
                site_key="hello",
                login_message="login",
                worker=worker,
            )
        self.assertEqual(result, "ok")
        self.assertEqual(session.seen, ("a", "ap", first))

    def test_need_login_false_passes_none_without_reading_current_account(self):
        holder = SimpleNamespace(current=SimpleNamespace(session_manager=Mock()))
        thread = _thread()
        with patch("app.utils.campus_job.accounts", holder):
            result = run_campus_job(
                thread, site_key="unused", login_message="unused",
                need_login=False, worker=lambda session: session,
            )
        self.assertIsNone(result)
        holder.current.session_manager.assert_not_called()
        thread.canceled.emit.assert_not_called()

    def test_need_login_false_works_without_account(self):
        thread = _thread()
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = None
            self.assertEqual(
                run_campus_job(thread, site_key="unused", login_message="unused",
                               need_login=False, worker=lambda session: session),
                None,
            )
        thread.canceled.emit.assert_not_called()

    def test_cancel_after_login_skips_worker_and_signals_once(self):
        worker = Mock()
        thread = _thread()
        account = SimpleNamespace(
            username="u", password="p",
            session_manager=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(
                    ensure_login=lambda *args, **kwargs: setattr(thread, "can_run", False)),
                mfa_provider=None,
            ),
        )
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = account
            result = run_campus_job(thread, site_key="hello", login_message="login", worker=worker)
        self.assertIs(result, JOB_FAILED)
        worker.assert_not_called()
        thread.canceled.emit.assert_called_once()
        self.assertFalse(thread.can_run)

    def test_cancel_after_worker_discards_result_and_signals_once(self):
        thread = _thread()

        def worker(_session):
            thread.can_run = False
            return "stale"

        account = SimpleNamespace(
            username="u", password="p",
            session_manager=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(ensure_login=Mock()), mfa_provider=None,
            ),
        )
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = account
            result = run_campus_job(thread, site_key="hello", login_message="login", worker=worker)
        self.assertIs(result, JOB_FAILED)
        thread.canceled.emit.assert_called_once()

    def test_mfa_102_targets_captured_account_after_switch(self):
        first = SimpleNamespace(
            username="a", password="ap", MFASignal=Mock(),
            session_manager=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(
                    ensure_login=lambda *args, **kwargs: (
                        setattr(holder, "current", second),
                        (_ for _ in ()).throw(ServerError(102, "mfa")),
                    )[-1]),
                mfa_provider=None,
            ),
        )
        second = SimpleNamespace(username="b", password="bp", MFASignal=Mock())
        holder = SimpleNamespace(current=first)
        thread = _thread()
        with patch("app.utils.campus_job.accounts", holder):
            result = run_campus_job(thread, site_key="hello", login_message="login",
                                    worker=Mock())
        self.assertIs(result, JOB_FAILED)
        first.MFASignal.emit.assert_called_once_with(True)
        second.MFASignal.emit.assert_not_called()
        thread.canceled.emit.assert_called_once()

    def test_each_exception_branch_emits_one_error_and_one_cancel(self):
        exceptions = (
            (MFACancelledError("cancel"), "安全验证已取消"),
            (MFAUnavailableError("missing"), "登录问题"),
            (QRCodeLoginCancelledError("cancel"), "扫码登录已取消"),
            (QRCodeLoginUnavailableError("missing"), "登录问题"),
            (ServerError(500, "server"), "服务器错误"),
            (requests.ConnectionError("offline"), "无网络连接"),
            (requests.Timeout("slow"), "网络错误"),
            (RuntimeError("unknown"), "其他错误"),
        )
        for error, title in exceptions:
            with self.subTest(error=type(error).__name__):
                thread = _thread()
                account = SimpleNamespace(
                    username="u", password="p", MFASignal=Mock(),
                    session_manager=SimpleNamespace(
                        get_session=lambda _: SimpleNamespace(
                            ensure_login=Mock(side_effect=error)),
                        mfa_provider=None,
                    ),
                )
                with patch("app.utils.campus_job.accounts") as accounts:
                    accounts.current = account
                    result = run_campus_job(thread, site_key="hello", login_message="login",
                                            worker=Mock())
                self.assertIs(result, JOB_FAILED)
                thread.error.emit.assert_called_once()
                self.assertEqual(thread.error.emit.call_args.args[0], title)
                thread.canceled.emit.assert_called_once()

    def test_worker_exception_emits_error_and_cancel_without_result(self):
        account = SimpleNamespace(
            username="u", password="p", MFASignal=Mock(),
            session_manager=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(ensure_login=Mock()),
                mfa_provider=None,
            ),
        )
        thread = _thread()
        worker = Mock(side_effect=RuntimeError("worker failed"))
        with patch("app.utils.campus_job.accounts") as accounts:
            accounts.current = account
            result = run_campus_job(thread, site_key="hello", login_message="login", worker=worker)
        self.assertIs(result, JOB_FAILED)
        worker.assert_called_once()
        thread.error.emit.assert_called_once_with("其他错误", "worker failed")
        thread.canceled.emit.assert_called_once()


class CampusFeatureThreadTest(unittest.TestCase):
    def test_none_result_is_success_and_emits_finished(self):
        thread = CampusFeatureThread("site", "login", Mock())
        result = Mock()
        finished = Mock()
        thread.result.connect(result)
        thread.hasFinished.connect(finished)
        with patch("app.threads.CampusFeatureThread.run_campus_job", return_value=None):
            thread.run()
        result.assert_called_once_with(None)
        finished.assert_called_once()

    def test_failed_job_emits_no_result_or_finished(self):
        thread = CampusFeatureThread("site", "login", Mock())
        result = Mock()
        finished = Mock()
        thread.result.connect(result)
        thread.hasFinished.connect(finished)
        with patch("app.threads.CampusFeatureThread.run_campus_job", return_value=JOB_FAILED):
            thread.run()
        result.assert_not_called()
        finished.assert_not_called()


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in tuple(self.slots):
            slot(*args)


class _FakeCampusThread:
    def __init__(self, *args, **kwargs):
        self.can_run = True
        self.result = _FakeSignal()
        self.error = _FakeSignal()
        self.started = False
        self.running = True

    def isRunning(self):
        return self.running

    def start(self):
        self.started = True


class CampusPageJobGuardTest(unittest.TestCase):
    def _page(self, account):
        from app.components.CampusPage import CampusPage

        page = SimpleNamespace(
            thread=None,
            processWidget=None,
            jobLayout=SimpleNamespace(addWidget=Mock()),
            _job_generation=0,
            warn=Mock(),
            on_account_changed=Mock(),
        )
        accounts = SimpleNamespace(current=account)
        return page, accounts, CampusPage

    def test_switching_account_discards_old_result_and_error(self):
        first = SimpleNamespace(uuid="first")
        second = SimpleNamespace(uuid="second")
        page, accounts, CampusPage = self._page(first)
        result = Mock()
        with patch("app.components.CampusPage.accounts", accounts), \
             patch("app.components.CampusPage.CampusFeatureThread", _FakeCampusThread), \
             patch("app.components.CampusPage.ProcessWidget", return_value=SimpleNamespace(deleteLater=Mock())):
            CampusPage.start_job(page, "hello", "login", Mock(), result, show_process=False)
            old_thread = page.thread
            accounts.current = second
            CampusPage._on_current_account_changed(page)
            old_thread.result.emit("stale result")
            old_thread.error.emit("stale error", "stale message")
        result.assert_not_called()
        page.warn.assert_not_called()
        self.assertFalse(old_thread.can_run)

    def test_starting_second_job_invalidates_first(self):
        account = SimpleNamespace(uuid="account")
        page, accounts, CampusPage = self._page(account)
        with patch("app.components.CampusPage.accounts", accounts), \
             patch("app.components.CampusPage.CampusFeatureThread", _FakeCampusThread):
            CampusPage.start_job(page, "one", "login", Mock(), Mock(), show_process=False)
            first_thread = page.thread
            CampusPage.start_job(page, "two", "login", Mock(), Mock(), show_process=False)
        self.assertFalse(first_thread.can_run)
        self.assertIsNot(page.thread, first_thread)

    def test_current_job_can_update_only_current_account(self):
        account = SimpleNamespace(uuid="account")
        page, accounts, CampusPage = self._page(account)
        result = Mock()
        with patch("app.components.CampusPage.accounts", accounts), \
             patch("app.components.CampusPage.CampusFeatureThread", _FakeCampusThread):
            CampusPage.start_job(page, "hello", "login", Mock(), result, show_process=False)
            page.thread.result.emit(None)
        result.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
