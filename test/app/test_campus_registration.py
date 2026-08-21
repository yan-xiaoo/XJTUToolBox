import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.FitnessInterface import FitnessInterface
from app.HomeInterface import HomeFrame
from app.JiaoxiaozhiInterface import JiaoxiaozhiInterface
from app.ProfileInterface import ProfileInterface
from app.SchoolCalendarInterface import SchoolCalendarInterface
from app.main_window import registerSession
from app.sessions.fitness_session import FitnessSession
from app.sessions.hello_session import HelloSession
from app.utils.session_manager import SessionManager


APP = QApplication.instance() or QApplication([])


class CampusRegistrationSmokeTest(unittest.TestCase):
    def test_hello_and_fitness_register_under_exact_keys(self):
        registerSession()
        self.assertIs(SessionManager.sessions["hello"], HelloSession)
        self.assertIs(SessionManager.sessions["fitness"], FitnessSession)

    def test_four_pages_construct_with_unique_object_names(self):
        pages = [ProfileInterface(), FitnessInterface(), SchoolCalendarInterface(), JiaoxiaozhiInterface()]
        for page in pages:
            page.close()
        self.assertEqual(len({page.objectName() for page in pages}), 4)

    def test_home_card_ids_and_callbacks_target_new_pages(self):
        frame = HomeFrame.__new__(HomeFrame)
        frame.main_window = type("Main", (), {
            "profile_interface": object(),
            "fitness_interface": object(),
            "school_calendar_interface": object(),
            "jiaoxiaozhi_interface": object(),
            "switchTo": Mock(),
        })()
        frame.tr = lambda text: text
        frame.linkCardView = Mock()
        frame.setupCards()
        cards = frame.linkCardView.setAvailableCards.call_args.args[0]
        self.assertEqual(len(cards), len(set(cards)))
        for key in ("profile", "fitness", "school_calendar", "jiaoxiaozhi"):
            self.assertIn(key, cards)
            cards[key]["callback"]()

    def test_new_modules_import_without_qt6_webengine(self):
        for name in (
            "app.ProfileInterface", "app.FitnessInterface", "app.SchoolCalendarInterface",
            "app.JiaoxiaozhiInterface", "hello.profile", "fitness.score", "jwxt.calendar",
        ):
            with self.subTest(name=name):
                __import__(name)


if __name__ == "__main__":
    unittest.main()
