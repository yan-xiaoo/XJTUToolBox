import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import QApplication

from app.FitnessInterface import FitnessInterface
from app.ProfileInterface import ProfileInterface
from app.SchoolCalendarInterface import SchoolCalendarInterface
from jwxt.calendar import CalendarHoliday, CalendarTerm
from fitness.score import FitnessItem, FitnessScore, FitnessYear
from hello.profile import StudentProfile


APP = QApplication.instance() or QApplication([])


def _term(term_id="1", *, current_week=None, holidays=None):
    term = CalendarTerm(
        term_id=term_id,
        start_date="2024-02-26",
        end_date="2024-07-14",
        term_num="2",
        year_num="2023-2024",
        week_number="20",
        work_days="5",
        holidays=holidays or [],
    )
    if current_week is not None:
        term = SimpleNamespace(**vars(term), current_week=current_week)
    return term


class CampusPageLifecycleTest(unittest.TestCase):
    def tearDown(self):
        for widget in getattr(self, "widgets", []):
            widget.close()
            widget.deleteLater()
        APP.processEvents()

    def _track(self, *widgets):
        self.widgets = list(widgets)
        return widgets

    def test_each_page_auto_loads_once_and_repeated_show_does_not_request(self):
        account = SimpleNamespace(uuid="account")
        for page_type, method in (
            (ProfileInterface, "refresh"),
            (FitnessInterface, "load_years"),
            (SchoolCalendarInterface, "load_terms"),
        ):
            with self.subTest(page=page_type.__name__), patch(
                f"app.{page_type.__name__}.accounts",
                SimpleNamespace(current=account),
            ) as accounts:
                page = page_type()
                self._track(page)
                with patch.object(page, method) as loader:
                    page.showEvent(QShowEvent())
                    page.showEvent(QShowEvent())
                loader.assert_called_once()
                self.assertTrue(page._auto_loaded)

                page.on_account_changed()
                self.assertFalse(page._auto_loaded)
                accounts.current = None
                page.showEvent(QShowEvent())
                loader.assert_called_once()

    def test_fitness_checked_year_auto_queries_and_switch_queries_again(self):
        page = FitnessInterface()
        self._track(page)
        page._auto_loaded = True
        with patch("app.FitnessInterface.accounts", SimpleNamespace(current=SimpleNamespace(uuid="a"))), \
             patch.object(page, "query_score") as query:
            page._on_years([
                FitnessYear("2023", "2023-2024", False),
                FitnessYear("2024", "2024-2025", True),
            ])
            self.assertEqual(page.yearBox.currentData(), "2024")
            query.assert_called_once()
            query.reset_mock()
            page.yearBox.setCurrentIndex(0)
            query.assert_called_once()

    def test_unselected_fitness_year_warns_without_request(self):
        page = FitnessInterface()
        self._track(page)
        with patch("app.FitnessInterface.accounts", SimpleNamespace(current=SimpleNamespace(uuid="a"))), \
             patch.object(page, "start_job") as start, patch.object(page, "warn") as warn:
            page.query_score()
        start.assert_not_called()
        warn.assert_called_once()

    def test_calendar_invalid_index_does_not_change_table(self):
        page = SchoolCalendarInterface()
        self._track(page)
        page.table.setRowCount(2)
        page._show_term(-1)
        page._show_term(1)
        page._show_term(99)
        self.assertEqual(page.table.rowCount(), 2)

    def test_calendar_refresh_clears_old_rows_and_empty_response(self):
        page = SchoolCalendarInterface()
        self._track(page)
        with patch.object(page, "success"):
            page._on_terms([_term(holidays=[CalendarHoliday("holiday", "s", "e", "1", "")])])
            self.assertEqual(page.table.rowCount(), 1)
            page._on_terms([])
        self.assertEqual(page.table.rowCount(), 0)
        self.assertEqual(page.termBox.count(), 0)

    def test_calendar_out_of_term_summary_omits_current_week(self):
        page = SchoolCalendarInterface()
        self._track(page)
        term = _term(current_week=None)
        page.terms = [term]
        page._show_term(0)
        self.assertNotIn("当前约第", page.summary.text())

    def test_profile_refresh_and_bad_photo_clear_existing_photo(self):
        page = ProfileInterface()
        self._track(page)
        page.photo.setText("old photo")
        account_state = SimpleNamespace(current=SimpleNamespace(uuid="a"))
        with patch("app.ProfileInterface.accounts", account_state), \
             patch("app.components.CampusPage.accounts", account_state), \
             patch.object(page, "start_job") as start:
            page.refresh()
        self.assertEqual(page.photo.text(), "暂无照片")
        start.assert_called_once()

        profile = StudentProfile(*([""] * 19))
        with patch.object(page, "success"):
            page._on_result((profile, b"not-an-image"))
        self.assertEqual(page.photo.text(), "暂无照片")

    def test_background_failure_can_be_reported_without_stale_data(self):
        page = ProfileInterface()
        self._track(page)
        page.fields.setText("old sensitive data")
        page.on_account_changed()
        self.assertNotIn("old sensitive", page.fields.text())
        self.assertEqual(page.photo.text(), "暂无照片")


if __name__ == "__main__":
    unittest.main()
