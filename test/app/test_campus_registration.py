import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.FitnessInterface import FitnessInterface
from app.HomeInterface import HomeFrame, validate_card_ids
from app.ProfileInterface import ProfileInterface
from app.SchoolCalendarInterface import SchoolCalendarInterface
from app.main_window import registerSession
from app.sessions.fitness_session import FitnessSession
from app.sessions.hello_session import HelloSession
from app.utils.session_manager import SessionManager


if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
APP = QApplication.instance() or QApplication([])


class CampusRegistrationSmokeTest(unittest.TestCase):
    def test_hello_and_fitness_register_under_exact_keys(self):
        registerSession()
        self.assertIs(SessionManager.sessions["hello"], HelloSession)
        self.assertIs(SessionManager.sessions["fitness"], FitnessSession)

    def test_three_pages_construct_with_unique_object_names(self):
        pages = [ProfileInterface(), FitnessInterface(), SchoolCalendarInterface()]
        for page in pages:
            page.close()
        self.assertEqual(len({page.objectName() for page in pages}), 3)

    def test_home_card_ids_and_callbacks_target_new_pages(self):
        frame = HomeFrame.__new__(HomeFrame)
        frame.main_window = type("Main", (), {
            "profile_interface": object(),
            "fitness_interface": object(),
            "school_calendar_interface": object(),
            "switchTo": Mock(),
        })()
        frame.tr = lambda text: text
        frame.linkCardView = Mock()
        frame.setupCards()
        cards = frame.linkCardView.setAvailableCards.call_args.args[0]
        self.assertEqual(tuple(cards), validate_card_ids(cards.keys()))
        with self.assertRaises(ValueError):
            validate_card_ids(["duplicate", "duplicate"])
        for key in ("profile", "fitness", "school_calendar"):
            self.assertIn(key, cards)
            cards[key]["callback"]()
        self.assertEqual(
            [call.args[0] for call in frame.main_window.switchTo.call_args_list],
            [frame.main_window.profile_interface, frame.main_window.fitness_interface,
             frame.main_window.school_calendar_interface],
        )

    def test_source_and_frozen_resource_paths_resolve(self):
        from app.utils.resources import resource_path
        source = resource_path("assets/icons/login.png")
        self.assertTrue(source.is_absolute())
        self.assertTrue(source.is_file())
        with patch("app.utils.resources.sys._MEIPASS", "/tmp/frozen-root", create=True):
            self.assertEqual(resource_path("assets/icons/login.png"),
                             Path("/tmp/frozen-root/assets/icons/login.png"))

    def test_new_modules_import_without_qt6_webengine(self):
        for name in (
            "app.ProfileInterface", "app.FitnessInterface", "app.SchoolCalendarInterface",
            "hello.profile", "fitness.score", "jwxt.calendar",
        ):
            with self.subTest(name=name):
                __import__(name)


if __name__ == "__main__":
    unittest.main()
