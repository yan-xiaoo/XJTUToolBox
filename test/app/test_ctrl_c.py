import signal
import unittest
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"

from app.ctrl_c import install_ctrl_c_handler


class CtrlCHandlerTest(unittest.TestCase):
    @patch("app.ctrl_c.QTimer")
    @patch("app.ctrl_c.signal.signal")
    @patch("app.ctrl_c.signal.getsignal", return_value=signal.SIG_DFL)
    def test_ctrl_c_quits_once_and_restores_previous_handler(
        self,
        _getsignal,
        set_signal,
        timer_class,
    ):
        application = Mock()
        timer = timer_class.return_value
        controller = install_ctrl_c_handler(application, interval_ms=25)

        self.assertIsNotNone(controller)
        timer.setInterval.assert_called_once_with(25)
        timer.timeout.connect.assert_called_once()
        timer.start.assert_called_once_with()
        installed_handler = set_signal.call_args_list[0].args[1]

        installed_handler(signal.SIGINT, None)
        installed_handler(signal.SIGINT, None)
        application.quit.assert_called_once_with()

        controller.restore()
        timer.stop.assert_called_once_with()
        self.assertEqual(set_signal.call_args_list[-1].args, (signal.SIGINT, signal.SIG_DFL))

    @patch("app.ctrl_c.QTimer")
    def test_non_main_thread_installation_and_invalid_interval_are_safe(self, timer_class):
        application = Mock()
        with patch("app.ctrl_c.signal.signal", side_effect=ValueError("main thread only")):
            self.assertIsNone(install_ctrl_c_handler(application))

        with self.assertRaisesRegex(ValueError, "interval must be positive"):
            install_ctrl_c_handler(application, interval_ms=0)
        timer_class.return_value.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
