import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
