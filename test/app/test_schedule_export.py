import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from icalendar import Calendar
from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
APP = QApplication.instance() or QApplication([])

from app.ScheduleInterface import ScheduleInterface
from schedule.schedule_service import ScheduleService


class ScheduleExportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        with patch("app.ScheduleInterface.accounts", current=None):
            self.page = ScheduleInterface()
        self.addCleanup(QCoreApplication.sendPostedEvents, None, QEvent.DeferredDelete)
        self.addCleanup(self.page.deleteLater)
        self.addCleanup(self.page.close)
        self.service = ScheduleService(str(self.root / "schedule.db"))
        self.addCleanup(self.service.database.close)
        self.page.schedule_service = self.service
        self.service.setTermInfo("2026-2027-1", "2026-09-28", current=True)
        self.service.addCourse("大学物理", 1, 1, 2, "A-101", "", [1])
        self.service.addCourse("节假日课程", 4, 1, 2, "A-101", "", [1])
        self.service.addExamFromJson({"term_number": "2026-2027-1", "exams": [{
            "KCM": "高等数学", "KSSJMS": "2026-09-29 08:00-10:00", "ZWH": "12",
        }]})
        cache = self.enterContext(patch("app.ScheduleInterface.cacheManager"))
        cache.read_expire_json.return_value = None
        self.fetch = self.enterContext(patch.object(self.page.holiday_thread, "start"))

    def test_holiday_lookup_keeps_each_exports_alarm_choice(self):
        silent = self.root / "silent.ics"
        with_alarms = self.root / "alarms.ics"
        self.page.exportICS(str(silent), set_alarm=False)
        self.page.exportICS(str(with_alarms), set_alarm=True)
        self.page.holiday_thread.result.emit([datetime.date(2026, 10, 1)])

        for path, expected in [(silent, [[], []]), (with_alarms, [[-15], [-30]])]:
            with self.subTest(file=path.name):
                events = Calendar.from_ical(path.read_bytes()).walk("VEVENT")
                self.assertEqual([str(e["SUMMARY"]) for e in events], ["大学物理", "高等数学考试"])
                self.assertEqual([
                    [alarm.decoded("TRIGGER").total_seconds() / 60 for alarm in e.walk("VALARM")]
                    for e in events
                ], expected)
        self.fetch.assert_called_once_with()

    def test_holiday_failure_does_not_replay_failed_export_on_retry(self):
        first = self.root / "first.ics"
        retry = self.root / "retry.ics"
        self.page.exportICS(str(first))
        self.page.holiday_thread.error.emit("", "未获取到节假日")
        self.page.exportICS(str(retry), set_alarm=False)
        self.page.holiday_thread.result.emit([])
        self.assertFalse(first.exists())
        self.assertTrue(retry.is_file())
        self.assertEqual(self.fetch.call_count, 2)

    def test_term_change_does_not_export_new_term_into_previous_file(self):
        target = self.root / "original.ics"
        self.page.exportICS(str(target))
        self.service.setTermInfo("2026-2027-2", "2027-03-01", current=True)
        with patch.object(self.page, "error") as error:
            self.page.holiday_thread.result.emit([])
        self.assertFalse(target.exists())
        error.assert_called_once()

    def test_write_failure_does_not_skip_next_export(self):
        good = self.root / "course.ics"
        self.page.exportICS(str(self.root / "missing-dir" / "course.ics"))
        self.page.exportICS(str(good))
        with patch.object(self.page, "error") as error:
            self.page.holiday_thread.result.emit([])
        self.assertTrue(good.is_file())
        error.assert_called_once()
