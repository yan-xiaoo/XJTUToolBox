import os
import unittest
import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QShowEvent
from PyQt5.QtWidgets import QApplication, QWidget

from app.FitnessInterface import FitnessInterface
from app.ProfileInterface import ProfileInterface
from app.SchoolCalendarInterface import SchoolCalendarInterface
from jwxt.calendar import CalendarImage
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


def _image(year="2026-2027", url="https://dean.xjtu.edu.cn/2026-2027.jpg"):
    return CalendarImage(year=year, url=url)


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

    def test_calendar_auto_loads_once_without_any_account(self):
        """校历读取的是公开的教务处页面，没有账号也应当自动加载，且不需要登录。"""
        page = SchoolCalendarInterface()
        self._track(page)
        with patch.object(page, "load_calendar") as loader:
            page.showEvent(QShowEvent())
            page.showEvent(QShowEvent())
        loader.assert_called_once()
        self.assertTrue(page._auto_loaded)

        page.on_account_changed()
        self.assertFalse(page._auto_loaded)
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

    def test_fitness_year_failure_allows_auto_reload_on_next_show(self):
        """体测学年加载失败后，下次进入页面应当再次自动加载。"""
        page = FitnessInterface()
        self._track(page)
        account_state = SimpleNamespace(current=SimpleNamespace(uuid="account"))
        with patch("app.FitnessInterface.accounts", account_state), \
             patch("app.components.CampusPage.accounts", account_state), \
             patch("app.components.CampusPage.CampusFeatureThread", _PageThread), \
             patch("app.components.CampusPage.ProcessWidget", _ProcessWidget):
            page.showEvent(QShowEvent())
            self.assertTrue(page._auto_loaded)
            page.thread.canceled.emit()
            self.assertFalse(page._auto_loaded)
            page.showEvent(QShowEvent())
            self.assertTrue(page._auto_loaded)

    def test_fitness_score_result_replaces_existing_cells(self):
        page = FitnessInterface()
        self._track(page)
        page._on_score(FitnessScore("1", "Alice", "90", "A", "r", "ok", "F", "4", [
            FitnessItem("bmi", "身高体重", "90", "A", "x"),
        ]))
        self.assertEqual(page.table.item(0, 1).text(), "90")
        page._on_score(FitnessScore("1", "Alice", "0", "B", "r", "ok", "F", "4", []))
        self.assertEqual(page.table.rowCount(), 0)

    def test_fitness_style_class_colors_grade_without_extra_column(self):
        page = FitnessInterface()
        self._track(page)
        with patch.object(page, "success"):
            page._on_score(FitnessScore("1", "Alice", "90", "A", "r", "ok", "F", "4", [
                FitnessItem("bmi", "身高体重", "90", "正常", "red"),
                FitnessItem("run", "跑步", "88", "良好", "red; color: blue"),
            ]))

        self.assertEqual(page.table.columnCount(), 3)
        self.assertEqual(
            [page.table.horizontalHeaderItem(column).text() for column in range(3)],
            ["项目", "成绩", "等级"],
        )
        self.assertNotIn(
            "red",
            [
                page.table.item(row, column).text()
                for row in range(page.table.rowCount())
                for column in range(page.table.columnCount())
            ],
        )
        self.assertEqual(page.table.item(0, 2).foreground().color(), QColor("red"))
        self.assertEqual(page.table.item(1, 2).foreground().style(), Qt.NoBrush)

    def test_unselected_fitness_year_warns_without_request(self):
        page = FitnessInterface()
        self._track(page)
        with patch("app.FitnessInterface.accounts", SimpleNamespace(current=SimpleNamespace(uuid="a"))), \
             patch.object(page, "start_job") as start, patch.object(page, "warn") as warn:
            page.query_score()
        start.assert_not_called()
        warn.assert_called_once()

    def test_calendar_images_fill_the_year_selector(self):
        page = SchoolCalendarInterface()
        self._track(page)
        with patch.object(page, "start_job") as start, patch.object(page, "success"):
            page._on_images([_image(), _image(year=None, url="https://dean.xjtu.edu.cn/upload.png")])
        self.assertEqual(page.yearBox.count(), 2)
        self.assertEqual(page.yearBox.itemText(0), "2026-2027 学年")
        self.assertEqual(page.yearBox.itemText(1), "未标注学年")
        # 选中学年后会去下载对应的图片
        self.assertEqual(start.call_count, 1)

    def test_calendar_empty_response_warns_instead_of_reporting_success(self):
        """回归：校历数据为空时曾经也提示“查询成功”。"""
        page = SchoolCalendarInterface()
        self._track(page)
        with patch.object(page, "success") as success, patch.object(page, "warn") as warn:
            page._on_images([])
        success.assert_not_called()
        warn.assert_called_once()
        self.assertEqual(page.yearBox.count(), 0)
        self.assertEqual(page.images, [])

    def test_calendar_invalid_image_index_is_ignored(self):
        page = SchoolCalendarInterface()
        self._track(page)
        page.images = [_image()]
        with patch.object(page, "start_job") as start:
            page._show_image(-1)
            page._show_image(1)
            page._show_image(99)
        start.assert_not_called()

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
