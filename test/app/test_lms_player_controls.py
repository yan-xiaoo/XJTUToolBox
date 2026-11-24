"""Playback controls must stay below the picture and seek only on a click/drag."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from app.sub_interfaces.lms.video_page import LMSVideoPage

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True


class LMSPlayerControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        setTheme(Theme.LIGHT)
        self.page = LMSVideoPage()
        self.page.resize(900, 700)
        self.page.show()
        QTest.qWait(30)
        self.bar = self.page.videoWidget.playBar

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        QTest.qWait(30)

    def test_controls_remain_below_video_when_mouse_leaves(self):
        picture = self.page.videoWidget
        self.assertIs(self.bar.parentWidget(), picture.parentWidget())
        self.assertGreaterEqual(self.bar.y(), picture.y() + picture.height())
        picture._onHideTimeOut()
        self.assertTrue(self.bar.isVisible())
        self.assertEqual(self.bar.opacityEffect.opacity(), 1)

    def test_hover_never_seeks_but_click_still_does(self):
        slider = self.bar.progressSlider
        slider.setRange(0, 100)
        slider.setValue(20)
        moves, clicks = QSignalSpy(slider.sliderMoved), QSignalSpy(slider.clicked)
        event = QMouseEvent(QEvent.MouseMove, QPointF(slider.width() * 3 // 4, slider.height() // 2),
                            Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(slider, event)
        QTest.qWait(20)
        self.assertFalse(slider.hasMouseTracking())
        self.assertEqual(slider.value(), 20)
        self.assertEqual(len(moves), 0)
        self.assertEqual(len(clicks), 0)
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(slider.width() // 2, slider.height() // 2))
        self.assertEqual(len(clicks), 1)
        self.assertGreater(slider.value(), 20)


    def test_backend_unknown_position_does_not_overflow_slider(self):
        errors = []
        original_hook = sys.excepthook
        try:
            sys.excepthook = lambda *args: errors.append(args)
            self.page.videoWidget.player.positionChanged.emit(-(2**63))
        finally:
            sys.excepthook = original_hook
        self.assertEqual(errors, [], "Qt's unknown position must not reach the 32-bit slider")

    def test_video_background_stays_black_in_both_themes(self):
        view = self.page.videoWidget
        self.assertEqual(view.backgroundBrush().color().name(), "#000000")
        self.assertEqual(view.viewport().size(), view.size())
        setTheme(Theme.DARK)
        self.assertEqual(view.backgroundBrush().color().name(), "#000000")
        setTheme(Theme.LIGHT)
        self.assertEqual(view.backgroundBrush().color().name(), "#000000")


def load_tests(loader, tests, pattern):
    # Qt's native multimedia service needs a fresh QApplication, like the decoder tests.
    if os.environ.get("LMS_PLAYER_CONTROLS_CHILD"):
        return loader.loadTestsFromTestCase(LMSPlayerControlsTest)

    def run_controls():
        environment = os.environ | {"LMS_PLAYER_CONTROLS_CHILD": "1", "PYTHONUTF8": "1",
                                   "QT_QPA_PLATFORM": "offscreen", "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", __name__, "-v"],
                                cwd=Path(__file__).resolve().parents[2], env=environment,
                                capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        print(result.stderr, end="", flush=True)

    return unittest.TestSuite([unittest.FunctionTestCase(run_controls, description="LMS player control regressions")])


if __name__ == "__main__":
    unittest.main()
