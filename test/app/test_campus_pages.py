import os
import unittest
import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import QApplication, QWidget

from app.FitnessInterface import FitnessInterface
from app.ProfileInterface import ProfileInterface
from app.SchoolCalendarInterface import SchoolCalendarInterface
from jwxt.calendar import CalendarHoliday, CalendarTerm
from fitness.score import FitnessItem, FitnessScore, FitnessYear
from hello.profile import StudentProfile


if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
APP = QApplication.instance() or QApplication([])


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in tuple(self.slots):
            slot(*args)


class _PageThread:
    def __init__(self, *args, **kwargs):
        self.can_run = True
        self.result = _Signal()
        self.error = _Signal()
        self.hasFinished = _Signal()
        self.canceled = _Signal()
        self.started = False

    def isRunning(self):
        return self.started

    def start(self):
        self.started = True


class _ProcessWidget(QWidget):
    def __init__(self, *args, **kwargs):
        parent = args[1] if len(args) > 1 and isinstance(args[1], QWidget) else None
        super().__init__(parent)


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
            page._on_score(FitnessScore("2", "Alice", "88", "B", "r", "ok", "F", "4", [
                FitnessItem("run", "跑步", "88", "B", "免测"),
            ]))
            self.assertEqual(page.table.item(0, 1).text(), "88")

    def test_fitness_score_result_replaces_existing_cells(self):
        page = FitnessInterface()
        self._track(page)
        page._on_score(FitnessScore("1", "Alice", "90", "A", "r", "ok", "F", "4", [
            FitnessItem("bmi", "身高体重", "90", "A", "x"),
        ]))
        self.assertEqual(page.table.item(0, 1).text(), "90")
        page._on_score(FitnessScore("1", "Alice", "0", "B", "r", "ok", "F", "4", []))
        self.assertEqual(page.table.rowCount(), 0)

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

    def test_profile_valid_photo_is_loaded_and_scaled(self):
        page = ProfileInterface()
        self._track(page)
        profile = StudentProfile(*([""] * 19))
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        with patch.object(page, "success"), patch.object(page.photo, "setPixmap") as set_pixmap, \
             patch("app.ProfileInterface.QPixmap") as pixmap_type:
            pixmap = pixmap_type.return_value
            pixmap.loadFromData.return_value = True
            scaled = pixmap.scaled.return_value
            page._on_result((profile, png))
        pixmap.loadFromData.assert_called_once_with(png)
        pixmap.scaled.assert_called_once_with(
            140, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        set_pixmap.assert_called_once_with(scaled)

    def test_profile_download_failure_returns_empty_photo(self):
        page = ProfileInterface()
        self._track(page)
        account_state = SimpleNamespace(current=SimpleNamespace(uuid="a"))
        profile = StudentProfile(*([""] * 19))
        with patch("app.ProfileInterface.accounts", account_state), \
             patch("app.components.CampusPage.accounts", account_state), \
             patch.object(page, "start_job") as start:
            page.refresh()
        worker = start.call_args.args[2]
        session = SimpleNamespace(get=Mock(side_effect=OSError("download")))
        with patch("app.ProfileInterface.HelloProfile.get_profile", return_value=profile):
            self.assertEqual(worker(session), (profile, b""))

    def test_profile_worker_error_clears_old_data_and_page_remains_operable(self):
        page = ProfileInterface()
        self._track(page)
        page.fields.setText("old sensitive data")
        page.photo.setText("old photo")
        account_state = SimpleNamespace(current=SimpleNamespace(uuid="a"))
        with patch("app.ProfileInterface.accounts", account_state), \
             patch("app.components.CampusPage.accounts", account_state), \
             patch("app.components.CampusPage.CampusFeatureThread", _PageThread), \
             patch("app.components.CampusPage.ProcessWidget", _ProcessWidget), \
             patch.object(page, "warn") as warn:
            page.refresh()
            page.thread.error.emit("查询失败", "offline")
        self.assertNotIn("old sensitive", page.fields.text())
        self.assertEqual(page.photo.text(), "暂无照片")
        self.assertTrue(page.refreshButton.isEnabled())
        warn.assert_called_once_with("查询失败", "offline")

    def test_profile_bad_photo_decode_clears_existing_photo(self):
        page = ProfileInterface()
        self._track(page)
        page.photo.setText("old photo")
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
