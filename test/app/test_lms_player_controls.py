"""Playback controls must stay below the picture and seek only on a click/drag."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QAbstractAnimation, QEvent, QPoint, QPointF, QRectF, QUrl, Qt
from PyQt5.QtGui import QImage, QMouseEvent
from PyQt5.QtMultimedia import QMediaContent, QVideoFrame, QVideoSurfaceFormat
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from app.sub_interfaces.lms.video_page import LMSVideoPage, ReplayVideoWidget

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

    def test_fullscreen_and_escape_preserve_player_and_restore_controls(self):
        player = self.page.videoWidget.player
        self.page.fullScreenButton.click()
        dialog = self.page.fullScreenDialog
        dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
        self.assertTrue(dialog.isFullScreen())
        self.assertIs(self.page.videoWidget.player, player)
        animation = self.bar.opacityAni
        self.page.videoWidget._onHideTimeOut()
        animation.pause()
        animation.setCurrentTime(animation.duration() // 2)
        self.assertTrue(self.bar.isVisible())
        self.assertGreater(self.bar.opacityEffect.opacity(), 0)
        self.assertLess(self.bar.opacityEffect.opacity(), 1)
        animation.setCurrentTime(animation.duration())
        self.assertTrue(self.bar.isHidden())
        event = QMouseEvent(QEvent.MouseMove, QPointF(40, 40), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.page.videoWidget.viewport(), event)
        animation.pause()
        animation.setCurrentTime(animation.duration() // 2)
        self.assertTrue(self.bar.isVisible())
        self.assertGreater(self.bar.opacityEffect.opacity(), 0)
        self.assertLess(self.bar.opacityEffect.opacity(), 1)
        animation.setCurrentTime(animation.duration())
        QTest.keyClick(dialog, Qt.Key_Escape)
        dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
        QApplication.processEvents()
        self.assertIsNone(self.page.fullScreenDialog)
        self.assertGreaterEqual(self.bar.y(), self.page.videoWidget.y() + self.page.videoWidget.height())
        self.assertTrue(self.bar.isVisible())

    def test_leaving_page_closes_fullscreen_and_releases_media(self):
        fixture = Path(__file__).with_name("fixtures") / "playback-h264.mp4"
        self.page.videoWidget.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(fixture))))
        self.page.fullScreenButton.click()
        QTest.qWait(30)
        self.page.hide()
        QTest.qWait(30)
        self.assertIsNone(self.page.fullScreenDialog)
        self.assertTrue(self.page.videoWidget.player.media().isNull())

    def test_exit_fade_does_not_restart_media_that_ends_during_the_transition(self):
        self.page.fullScreenButton.click()
        dialog = self.page.fullScreenDialog
        dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
        player = self.page.videoWidget.player
        # Simulate the backend reaching EndOfMedia while the real dialog fades out.
        with patch.object(player, "isPlaying", return_value=True) as playing, \
                patch.object(player, "play") as play, patch.object(player, "pause") as pause:
            dialog.reject()
            playing.return_value = False
            dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
            self.assertIsNone(self.page.fullScreenDialog)
            self.assertFalse(dialog.wasPlaying)
            play.assert_not_called()
            pause.assert_not_called()

    def test_fullscreen_does_not_play_or_pause_inactive_media(self):
        player = self.page.videoWidget.player
        with patch.object(player, "isPlaying", return_value=False), \
                patch.object(player, "play") as play, patch.object(player, "pause") as pause:
            self.page.fullScreenButton.click()
            dialog = self.page.fullScreenDialog
            dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
            dialog.reject()
            dialog.transitionAnimation.setCurrentTime(dialog.transitionAnimation.duration())
            self.assertIsNone(self.page.fullScreenDialog)
            self.assertIs(self.page.videoWidget.player, player)
            self.assertTrue(self.bar.isVisible())
            play.assert_not_called()
            pause.assert_not_called()

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

    def test_fullscreen_is_borderless_and_fades_in_and_out(self):
        self.page.fullScreenButton.click()
        dialog = self.page.fullScreenDialog
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        animation = dialog.transitionAnimation
        animation.pause()
        animation.setCurrentTime(animation.duration() // 2)
        self.assertGreater(dialog.windowOpacity(), 0)
        self.assertLess(dialog.windowOpacity(), 1)
        animation.setCurrentTime(200)
        self.assertLess(dialog.windowOpacity(), 1, "The full-screen transition should still be visible at 200ms")
        animation.setCurrentTime(animation.duration())
        self.assertEqual(dialog.frameGeometry(), dialog.screen().geometry())
        self.assertEqual(dialog.windowOpacity(), 1)
        dialog.reject()
        animation.pause()
        animation.setCurrentTime(animation.duration() // 2)
        self.assertTrue(dialog.isVisible())
        self.assertGreater(dialog.windowOpacity(), 0)
        self.assertLess(dialog.windowOpacity(), 1)
        animation.setCurrentTime(animation.duration())
        self.assertIsNone(self.page.fullScreenDialog)

    def test_fullscreen_cover_has_no_empty_pixels_and_normal_mode_restores_aspect(self):
        # Qt's documented videoSurface API supplies a local 4:3 frame in a 16:9 view.
        view = ReplayVideoWidget()
        try:
            view.resize(801, 451)
            view.show()
            image = QImage(640, 480, QImage.Format_ARGB32)
            image.fill(Qt.blue)
            surface = view.videoItem.videoSurface()
            self.assertTrue(surface.start(QVideoSurfaceFormat(image.size(), QVideoFrame.Format_ARGB32)))
            self.assertTrue(surface.present(QVideoFrame(image)))
            QTest.qWait(30)
            view.setFullScreenMode(True)
            QTest.qWait(30)
            bounds = view.viewportTransform().mapRect(view.videoItem.boundingRect())
            self.assertEqual(bounds, QRectF(view.viewport().rect()))
            rendered = view.viewport().grab().toImage()
            for x, y in ((0, 0), (800, 0), (0, 450), (800, 450)):
                self.assertEqual(rendered.pixelColor(x, y).name(), "#0000ff", "Full-screen video must reach every edge")
            view.setFullScreenMode(False)
            bounds = view.viewportTransform().mapRect(view.videoItem.boundingRect())
            self.assertAlmostEqual(bounds.center().x(), view.viewport().width() / 2, places=5)
            self.assertAlmostEqual(bounds.width() / bounds.height(), 4 / 3, places=5)
            surface.stop()
        finally:
            view.close()
            view.deleteLater()
            QTest.qWait(30)

    def test_mouse_activity_reverses_fade_before_its_first_tick(self):
        view = self.page.videoWidget
        view.setFullScreenMode(True)
        self.bar.fadeOut()
        self.assertEqual(self.bar.opacityEffect.opacity(), 1)
        self.assertEqual(self.bar.opacityAni.currentTime(), 0)
        view.showControls()
        self.assertEqual(self.bar.opacityAni.endValue(), 1)
        self.bar.opacityAni.setCurrentTime(self.bar.opacityAni.duration())
        self.assertTrue(self.bar.isVisible())
        self.assertEqual(self.bar.opacityEffect.opacity(), 1)

    def test_mouse_activity_can_reverse_fade_without_restarting_it_repeatedly(self):
        self.page.fullScreenButton.click()
        self.bar.fadeOut()
        self.bar.opacityAni.setCurrentTime(70)
        self.page.videoWidget.showControls()
        self.assertEqual(self.bar.opacityAni.endValue(), 1)
        self.bar.opacityAni.setCurrentTime(70)
        before = self.bar.opacityAni.currentTime()
        self.page.videoWidget.showControls()
        self.assertEqual(self.bar.opacityAni.currentTime(), before)
        self.bar.opacityAni.setCurrentTime(self.bar.opacityAni.duration())
        self.assertTrue(self.bar.isVisible())
        self.assertEqual(self.bar.opacityEffect.opacity(), 1)
        self.page.videoWidget._onHideTimeOut()
        self.bar.opacityAni.setCurrentTime(self.bar.opacityAni.duration() // 2)
        self.page.stopPlayback()
        self.assertEqual(self.bar.opacityAni.state(), QAbstractAnimation.Stopped)
        self.assertIsNone(self.page.fullScreenDialog)
        self.assertTrue(self.bar.isVisible())
        self.assertEqual(self.bar.opacityEffect.opacity(), 1)


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
