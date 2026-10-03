import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

from app.threads.EmptyRoomThread import EmptyRoomThread
from app.threads.ExamScheduleThread import ExamScheduleThread
from app.threads.GraduateScheduleThread import GraduateScheduleThread
from app.threads.GraduateScoreThread import GraduateScoreThread
from app.threads.JudgeThread import JudgeChoice, JudgeThread
from app.threads.LMSThread import LMSThread
from app.threads.ScheduleAttendanceThread import ScheduleAttendanceThread
from app.threads.ScheduleThread import ScheduleThread
from app.threads.ScoreThread import ScoreThread
from app.threads.VenueThread import VenueThread
from app.utils.account import request_mfa
from auth import ServerError


def _switch_and_raise(error, holder, new_current):
    """模拟登录请求进行中账户被移除/切换。"""

    def side_effect(*args, **kwargs):
        holder.current = new_current
        raise error

    return side_effect


class _SnapshotThenSwitch:
    """模拟「快照之后、登录之前」切换账户。

    第一次读取 ``current`` 返回 ``first``（run() 开头的快照），之后返回 ``second``，
    以此复现登录窗口内账户被切换的场景。
    """

    def __init__(self, first, second):
        self.first = first
        self.second = second
        self.reads = 0

    @property
    def current(self):
        self.reads += 1
        return self.first if self.reads == 1 else self.second


def _fake_account(username, password):
    """构造一个账户替身；其 session 明确 has_login=False 以便走到登录路径。"""
    session = Mock()
    session.has_login = False
    account = SimpleNamespace(
        username=username,
        password=password,
        type=None,
        POSTGRADUATE=None,
        MFASignal=Mock(),
        session_manager=Mock(),
    )
    account.session_manager.get_session.return_value = session
    return account, session


class RequestMFATest(unittest.TestCase):
    def test_none_account_is_ignored(self):
        request_mfa(None)  # 不应抛异常

    def test_account_is_notified(self):
        account = SimpleNamespace(MFASignal=Mock())
        request_mfa(account)
        account.MFASignal.emit.assert_called_once_with(True)


class MFA102TargetTest(unittest.TestCase):
    def test_account_removed_mid_login_still_reports_failure(self):
        """旧实现：accounts.current 为 None，AttributeError 逃出 run()，canceled 丢失。"""
        thread = ExamScheduleThread()
        errors, canceled = [], []
        thread.error.connect(lambda title, detail: errors.append((title, detail)))
        thread.canceled.connect(lambda: canceled.append(True))

        account = SimpleNamespace(
            username="u", password="p", MFASignal=Mock(), session_manager=Mock()
        )
        holder = SimpleNamespace(current=account)
        account.session_manager.get_session.return_value.ensure_login.side_effect = (
            _switch_and_raise(ServerError(102, "mfa"), holder, None)
        )

        with patch("app.threads.ExamScheduleThread.accounts", holder):
            thread.run()

        self.assertEqual(1, len(errors))
        self.assertEqual("登录问题", errors[0][0])
        self.assertEqual([True], canceled)
        account.MFASignal.emit.assert_called_once_with(True)

    def test_switch_mid_login_notifies_owning_account(self):
        """旧实现：MFA 信号会发给中途切换成的新账户。"""
        first = SimpleNamespace(
            username="a", password="ap", MFASignal=Mock(), session_manager=Mock()
        )
        second = SimpleNamespace(
            username="b", password="bp", MFASignal=Mock(), session_manager=Mock()
        )
        holder = SimpleNamespace(current=first)
        first.session_manager.get_session.return_value.ensure_login.side_effect = (
            _switch_and_raise(ServerError(102, "mfa"), holder, second)
        )

        thread = JudgeThread(first, JudgeChoice.GET_COURSES)
        canceled = []
        thread.canceled.connect(lambda: canceled.append(True))

        # 当前实现已不再从模块读取 accounts；create=True 保证同一用例在新旧实现上都能运行
        with patch("app.threads.JudgeThread.accounts", holder, create=True):
            thread.run()

        first.MFASignal.emit.assert_called_once_with(True)
        second.MFASignal.emit.assert_not_called()
        self.assertEqual([True], canceled)


class LoginUsesSnapshotTest(unittest.TestCase):
    """审查意见 P2：登录、session 获取与错误处理必须共用任务开始时的账户快照。

    旧实现中 ``session``/``login()`` 仍读取 ``accounts.current``，因此「快照后、登录前」
    切换账户会导致用新账户登录、却把 MFA 通知发给旧账户。
    """

    @staticmethod
    def _run_with_switch(thread, module, first, second, first_session):
        holder = _SnapshotThenSwitch(first, second)
        first_session.ensure_login.side_effect = ServerError(102, "mfa")
        errors, canceled = [], []
        thread.error.connect(lambda title, detail: errors.append((title, detail)))
        thread.canceled.connect(lambda: canceled.append(True))
        with patch(f"{module}.accounts", holder):
            thread.run()
        return errors, canceled, holder

    def _assert_snapshot_used(self, module, factory):
        first, first_session = _fake_account("a", "ap")
        second, _ = _fake_account("b", "bp")
        thread = factory()
        errors, canceled, holder = self._run_with_switch(
            thread, module, first, second, first_session
        )
        # 登录只发生在快照账户 A 的 session 上
        first_session.ensure_login.assert_called_once()
        self.assertEqual("a", first_session.ensure_login.call_args.args[0])
        # 切换后的账户 B 从未被取用
        second.session_manager.get_session.assert_not_called()
        # MFA 通知发给 A，而非 B
        first.MFASignal.emit.assert_called_once_with(True)
        second.MFASignal.emit.assert_not_called()
        self.assertEqual(1, len(errors))
        self.assertEqual([True], canceled)
        # 快照只读取一次 current，之后不再回退到全局当前账户
        self.assertEqual(1, holder.reads)

    def test_exam_schedule_thread(self):
        self._assert_snapshot_used("app.threads.ExamScheduleThread", ExamScheduleThread)

    def test_empty_room_thread(self):
        self._assert_snapshot_used("app.threads.EmptyRoomThread", EmptyRoomThread)

    def test_graduate_schedule_thread(self):
        self._assert_snapshot_used(
            "app.threads.GraduateScheduleThread", GraduateScheduleThread
        )

    def test_graduate_score_thread(self):
        self._assert_snapshot_used(
            "app.threads.GraduateScoreThread", GraduateScoreThread
        )

    def test_lms_thread(self):
        self._assert_snapshot_used("app.threads.LMSThread", LMSThread)

    def test_score_thread(self):
        self._assert_snapshot_used("app.threads.ScoreThread", ScoreThread)

    def test_schedule_attendance_thread(self):
        def factory():
            thread = ScheduleAttendanceThread()
            # run() 会先校验起止日期，必须预置为非 None 才会走到登录
            thread.start_date = "2026-01-01"
            thread.end_date = "2026-01-01"
            return thread

        self._assert_snapshot_used(
            "app.threads.ScheduleAttendanceThread", factory
        )

    def test_schedule_thread_login_uses_snapshot(self):
        # 該路徑先登入考勤系統並拋出 ServerError(102)，覆蓋 attendance session 的登入分支
        self._assert_snapshot_used("app.threads.ScheduleThread", ScheduleThread)

    def test_venue_thread_session_uses_snapshot(self):
        first, first_session = _fake_account("a", "ap")
        second, _ = _fake_account("b", "bp")
        thread = VenueThread()
        holder = _SnapshotThenSwitch(first, second)
        first_session.ensure_login.side_effect = ServerError(102, "mfa")
        errors, canceled = [], []
        thread.error.connect(lambda title, detail: errors.append((title, detail)))
        thread.canceled.connect(lambda: canceled.append(True))
        with patch("app.threads.VenueThread.accounts", holder):
            thread.run()
        # venue 无 MFA，但 session 必须仍取自快照账户 A
        first.session_manager.get_session.assert_called_once_with("venue")
        second.session_manager.get_session.assert_not_called()
        self.assertEqual([True], canceled)
        self.assertEqual(1, holder.reads)


if __name__ == "__main__":
    unittest.main()
