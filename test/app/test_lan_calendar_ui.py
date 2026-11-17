import datetime
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWidgets import QApplication, QWidget
from app.ScheduleInterface import ScheduleInterface
from app.sub_interfaces.CalendarSubscriptionDialog import CalendarSubscriptionDialog
from schedule.calendar_subscription import CalendarSubscription

APP = QApplication.instance() or QApplication([])


class SubscriptionUIFixture(QWidget):
    calendarSubscriptionChanged = pyqtSignal()
    _subscriptionData = ScheduleInterface._subscriptionData
    startCalendarSubscription = ScheduleInterface.startCalendarSubscription
    stopCalendarSubscription = ScheduleInterface.stopCalendarSubscription
    refreshCalendarSubscription = ScheduleInterface.refreshCalendarSubscription

    def __init__(self, directory):
        super().__init__()
        self.calendar_subscription = CalendarSubscription()
        self._subscription_timer = QTimer(self)
        self._subscription_context = None
        self._subscription_options = None
        self.context = (directory, "2026-2027-1")
        self._calendarContext = lambda: self.context
        self._subscriptionData = Mock(return_value=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
        self.error = Mock()


class SubscriptionUITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ui = SubscriptionUIFixture(self.tmp.name)
        self.addCleanup(self.ui.close)
        self.addCleanup(self.ui.stopCalendarSubscription)

    def test_dialog_off_by_default_and_options_are_editable(self):
        dialog = CalendarSubscriptionDialog(self.ui)
        self.addCleanup(dialog.reject)
        self.assertFalse(self.ui.calendar_subscription.running)
        self.assertFalse(dialog.copy.isEnabled())
        self.assertEqual(dialog.link.text(), "")
        self.assertTrue(dialog.address.isEnabled())

    def test_start_stop_updates_link_and_locks_options(self):
        dialog = CalendarSubscriptionDialog(self.ui)
        self.addCleanup(dialog.reject)
        self.ui.startCalendarSubscription("127.0.0.1", 0, False, False)
        self.assertTrue(dialog.copy.isEnabled())
        self.assertFalse(dialog.alarm.isEnabled())
        self.assertIn("/calendar.ics", dialog.link.text())
        self.assertFalse(self.ui._subscription_options[1])
        self.ui.stopCalendarSubscription()
        self.assertEqual(dialog.link.text(), "")
        self.assertFalse(dialog.copy.isEnabled())
        self.assertFalse(self.ui._subscription_timer.isActive())

    def test_reopened_dialog_shows_the_actual_running_options(self):
        self.ui.startCalendarSubscription("127.0.0.1", 0, False, False)
        dialog = CalendarSubscriptionDialog(self.ui)
        self.addCleanup(dialog.reject)
        self.assertEqual(dialog.address.currentText(), "127.0.0.1")
        self.assertEqual(dialog.port.value(), self.ui.calendar_subscription._server.server_port)
        self.assertFalse(dialog.alarm.isChecked())
        self.assertFalse(dialog.holiday.isChecked())
        self.assertFalse(dialog.port.isEnabled())

    def test_account_or_term_change_stops_feed(self):
        self.ui.startCalendarSubscription("127.0.0.1", 0, False, True)
        self.ui.context = (self.tmp.name, "2026-2027-2")
        self.ui.refreshCalendarSubscription()
        self.assertFalse(self.ui.calendar_subscription.running)
        self.assertIsNone(self.ui.calendar_subscription._data)

    def test_failed_refresh_stops_instead_of_serving_stale_data(self):
        self.ui.startCalendarSubscription("127.0.0.1", 0, False, True)
        self.ui._subscriptionData.side_effect = ValueError("missing term")
        self.ui.refreshCalendarSubscription()
        self.assertFalse(self.ui.calendar_subscription.running)
        self.ui.error.assert_called_once()

    def test_missing_holiday_cache_does_not_start_listener(self):
        with patch("app.ScheduleInterface.cacheManager.read_expire_json", return_value=None):
            with self.assertRaises(ValueError):
                self.ui.startCalendarSubscription("127.0.0.1", 0, True, True)
        self.assertFalse(self.ui.calendar_subscription.running)

    def test_existing_export_calls_shared_serializer(self):
        target = Path(self.tmp.name) / "export.ics"
        fake = SimpleNamespace(schedule_service=object(), tr=lambda s: s, success=Mock())
        with patch("app.ScheduleInterface.build_calendar", return_value=b"calendar") as render:
            ScheduleInterface.export(fake, str(target), [], False)
        render.assert_called_once_with(fake.schedule_service, [], False, tr=fake.tr)
        self.assertEqual(target.read_bytes(), b"calendar")


if __name__ == "__main__":
    unittest.main()
