import os
import tempfile
import time
import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget
from xjtu_calendar.subscribe import SubscriptionState, save_state

from app.sub_interfaces.CalendarSubscriptionDialog import CalendarConfigurationDialog, CalendarSubscriptionDialog
from app.threads.CalendarThread import CalendarThread
from schedule.calendar_service import CalendarService
from test.schedule import test_calendar_service as fixtures
from app.ScheduleInterface import ScheduleInterface

START, TERM = fixtures.START, fixtures.TERM

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True
APP = QApplication.instance() or QApplication([])


class CalendarDialogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = CalendarService(self.temp.name, TERM)
        self.service.initialize(START)
        self.parent = QWidget()
        self.parent.resize(1000, 1000)
        self.addCleanup(self.parent.close)

    def test_unregistered_dialog_disables_remote_actions(self):
        dialog = CalendarSubscriptionDialog(self.service, None, self.parent)
        self.assertTrue(dialog.buttons["init"].isEnabled())
        self.assertFalse(dialog.buttons["push"].isEnabled())
        self.assertFalse(dialog.buttons["copy"].isEnabled())
        self.assertFalse(dialog.massCancellation.isChecked())
        self.assertTrue(dialog.includeExams.isChecked())

    def test_registered_dialog_displays_urls_and_locks_target(self):
        state = SubscriptionState(TERM, "https://github.com/example/calendar.git", "cal", "testtoken",
                                  "https://example.github.io/calendar/")
        save_state(self.service.settings("subscription"), state)
        dialog = CalendarSubscriptionDialog(self.service, None, self.parent)
        self.assertTrue(dialog.buttons["push"].isEnabled())
        self.assertFalse(dialog.buttons["init"].isEnabled())
        self.assertFalse(dialog.repo.isEnabled())
        dialog.run_action("copy")
        self.assertEqual(APP.clipboard().text(), state.subscription_url)
        dialog.run_action("webcal")
        self.assertEqual(APP.clipboard().text(), state.webcal_url)

    def test_invalid_editor_input_is_not_saved(self):
        before = self.service.calendar_path.read_bytes()
        dialog = CalendarConfigurationDialog(self.service, self.parent)
        dialog.editors[0].setPlainText("{")
        dialog.save()
        self.assertEqual(self.service.calendar_path.read_bytes(), before)
        self.assertTrue(dialog.errorLabel.text())

    def test_running_dialog_cannot_be_closed(self):
        dialog = CalendarSubscriptionDialog(self.service, None, self.parent)
        dialog.job = object()
        dialog.reject()
        self.assertIn("正在运行", dialog.status.text())
        dialog.job = None

    def test_thread_start_failure_unlocks_dialog(self):
        dialog = CalendarSubscriptionDialog(self.service, None, self.parent)
        dialog.repo.setText('https://github.com/example/calendar.git')
        with patch('app.sub_interfaces.CalendarSubscriptionDialog.CalendarThread') as thread:
            thread.return_value.start.side_effect = RuntimeError('cannot start')
            thread.return_value.isRunning.return_value = False
            dialog.run_action('init')
        self.assertIsNone(dialog.job)
        self.assertTrue(dialog.yesButton.isEnabled())
        self.assertTrue(dialog.buttons['init'].isEnabled())
        self.assertIn('cannot start', dialog.output.toPlainText())

    def test_account_change_invalidates_open_dialog(self):
        dialog = CalendarSubscriptionDialog(self.service, None, self.parent)
        dialog.on_account_changed()
        with patch('app.sub_interfaces.CalendarSubscriptionDialog.CalendarThread') as thread:
            dialog.run_action('init')
            thread.assert_not_called()
        self.assertFalse(dialog.buttons['init'].isEnabled())


class CalendarChildProcessTest(unittest.TestCase):
    def test_cancelled_holiday_worker_never_requests_network_or_emits_result(self):
        from app.threads.HolidayThread import HolidayThread
        thread = HolidayThread()
        results, errors = [], []
        thread.result.connect(results.append)
        thread.error.connect(lambda *args: errors.append(args))
        thread.cancel()
        with patch('app.threads.HolidayThread.get_session') as session:
            thread.run()
            session.return_value.__enter__.return_value.get.assert_not_called()
        self.assertEqual(results, [])
        self.assertEqual(errors, [])

    def test_unwritable_job_directory_returns_error(self):
        thread = CalendarThread({"action": "export", "home": "unwritable-calendar-home", "term": TERM})
        results = []
        thread.result.connect(results.append)
        with patch("app.threads.CalendarThread.Path.mkdir", side_effect=PermissionError("access denied")):
            thread.run()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIn("access denied", results[0]["message"])

    def test_source_app_dispatches_worker_without_opening_gui(self):
        fixture = fixtures.CalendarServiceTest()
        fixture.setUp()
        try:
            cfg = fixture.prepare("export")
            output = fixture.directory / "result.ics"
            thread = CalendarThread({"action": "export", "home": str(cfg.home), "term": TERM,
                                     "output": str(output), "alarm": False})
            results = []
            thread.result.connect(results.append)
            thread.start()
            deadline = time.monotonic() + 20
            while thread.isRunning() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(thread.wait(1000))
            APP.processEvents()
            self.assertTrue(results, "The child process did not return a result")
            self.assertTrue(results[0]["ok"], results[0])
            self.assertTrue(output.is_file())
            self.assertFalse(list(cfg.home.glob("job-*")))
        finally:
            fixture.doCleanups()


class CalendarExportLifecycleTest(unittest.TestCase):
    """Exercise the real export callbacks with isolated UI/network boundaries."""

    def test_previous_holiday_worker_cannot_complete_a_new_request(self):
        self.view.exportICS('second.ics', True, False)
        context = self.view._export_context
        self.view.sender = lambda: object()
        self.view.onReceiveHoliday([])
        self.view.onHolidayError('old', 'old error')
        self.assertIs(self.view._export_context, context)
        self.assertTrue(self.view._holiday_export_pending)
        self.thread.assert_not_called()

    def setUp(self):
        self.calendar = MagicMock(term=TERM)
        self.snapshot = {"courses": ["captured course"]}
        self.calendar.snapshot.return_value = self.snapshot
        self.calendar.prepare.return_value = SimpleNamespace(home="unused-job-home")
        self.view = SimpleNamespace(
            _export_context=None, _calendar_export_job=None, _holiday_export_pending=False,
            schedule_service=object(), stateToolTip=None, tr=lambda text: text,
            calendarService=lambda: self.calendar, exportAction=MagicMock(), calendarAction=MagicMock(),
            error=MagicMock(), onCalendarExportResult=MagicMock(),
        )
        for name in ("holiday_thread", "schedule_thread", "graduate_schedule_thread",
                     "schedule_exam_thread", "schedule_attendance_thread"):
            thread = MagicMock()
            thread.isRunning.return_value = False
            setattr(self.view, name, thread)
        self.view.week = 1
        self.view.getWeekLength = lambda: 20
        for name in ("getTableButton", "getWeekAttendanceButton", "getTablePrimaryButton",
                     "getWeekAttendancePrimaryButton", "lastWeekButton", "nextWeekButton", "weekComboBox",
                     "process_widget_attendance", "process_widget_ehall", "getExamAction", "changeTermAction", "clearAction"):
            setattr(self.view, name, MagicMock())
        for name in ("exportICS", "startCalendarExport", "export", "onReceiveHoliday",
                     "onHolidayError", "onCalendarExportFinished", "resetCalendarExport", "updateCalendarActions", "unlock"):
            setattr(self.view, name, MethodType(getattr(ScheduleInterface, name), self.view))
        self.read_cache = self.enterContext(patch("app.ScheduleInterface.cacheManager.read_expire_json", return_value=None))
        self.write_cache = self.enterContext(patch("app.ScheduleInterface.cacheManager.write_expire_json"))
        self.enterContext(patch("app.ScheduleInterface.StateToolTip"))
        self.holiday_factory = self.enterContext(patch('app.ScheduleInterface.HolidayThread', return_value=self.view.holiday_thread))
        self.thread = self.enterContext(patch("app.ScheduleInterface.CalendarThread"))

    def test_pending_holidays_reject_second_export_and_keep_original_options(self):
        self.view.exportICS("first.ics", True, False)
        context = self.view._export_context
        with self.assertRaisesRegex(ValueError, "正在运行"):
            self.view.exportICS("second.ics", False, True)
        self.assertIs(self.view._export_context, context)
        self.view.exportAction.setEnabled.assert_called_with(False)
        self.view.calendarAction.setEnabled.assert_called_with(False)
        self.view.schedule_service = object()  # An account change must not replace the captured data.
        self.view.onReceiveHoliday([START])
        self.calendar.prepare.assert_called_once_with(self.snapshot, "export", excluded_dates=[START])
        request = self.thread.call_args.args[0]
        self.assertEqual(request["output"], "first.ics")
        self.assertFalse(request["alarm"])
        self.thread.return_value.start.assert_called_once()

    def test_network_unlock_keeps_pending_export_disabled(self):
        self.view.exportICS("first.ics", True)
        self.view.unlock()
        self.view.exportAction.setEnabled.assert_called_with(False)

    def test_holiday_start_failure_cleans_up_and_allows_retry(self):
        self.view.holiday_thread.start.side_effect = RuntimeError("cannot start holiday fetch")
        with self.assertRaisesRegex(RuntimeError, "cannot start holiday fetch"):
            self.view.exportICS("first.ics", True)
        self.assertIsNone(self.view._export_context)
        self.assertIsNone(self.view.stateToolTip)
        self.assertFalse(self.view._holiday_export_pending)
        self.view.exportICS("retry.ics", False)
        self.thread.return_value.start.assert_called_once()

    def test_holiday_error_cleans_up_and_allows_retry(self):
        self.view.exportICS("first.ics", True)
        self.view.onHolidayError("", "network failed")
        self.assertIsNone(self.view._export_context)
        self.assertFalse(self.view._holiday_export_pending)
        self.view.exportAction.setEnabled.assert_called_with(True)
        self.view.exportICS("retry.ics", False)
        self.assertEqual(self.thread.call_args.args[0]["output"], "retry.ics")

    def test_late_or_duplicate_holiday_result_cannot_start_another_job(self):
        self.view.exportICS("first.ics", True)
        self.view.onReceiveHoliday([])
        self.view.onReceiveHoliday([])
        self.thread.assert_called_once()
        self.view.onCalendarExportFinished()
        self.view.onReceiveHoliday([])
        self.thread.assert_called_once()
        self.view.exportAction.setEnabled.assert_called_with(True)

    def test_prepare_failure_releases_pending_export(self):
        self.view.exportICS("first.ics", True)
        self.calendar.prepare.side_effect = ValueError("invalid calendar")
        self.view.onReceiveHoliday([])
        self.assertIsNone(self.view._export_context)
        self.assertIsNone(self.view._calendar_export_job)
        self.view.error.assert_called_once()
        self.view.exportAction.setEnabled.assert_called_with(True)

    def test_start_failure_releases_job_and_context(self):
        self.thread.return_value.start.side_effect = RuntimeError("cannot start")
        with self.assertRaisesRegex(RuntimeError, "cannot start"):
            self.view.exportICS("first.ics", False)
        self.assertIsNone(self.view._export_context)
        self.assertIsNone(self.view._calendar_export_job)

    def test_export_completion_does_not_unlock_another_running_operation(self):
        self.view.exportICS("first.ics", False)
        self.view.schedule_thread.isRunning.return_value = True
        self.view.onCalendarExportFinished()
        self.view.exportAction.setEnabled.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
