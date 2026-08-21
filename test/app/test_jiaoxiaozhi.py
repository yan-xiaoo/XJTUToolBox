import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import QApplication

from app.JiaoxiaozhiInterface import JiaoxiaozhiInterface
from app.school_ai_launcher import school_ai_browser_command
from app.school_ai_policy import JIAOXIAOZHI_URL


APP = QApplication.instance() or QApplication([])


class JiaoxiaozhiLauncherTest(unittest.TestCase):
    def test_source_environment_without_webengine_returns_none(self):
        with patch("app.school_ai_launcher.sys.frozen", False, create=True), \
             patch("app.school_ai_launcher.importlib.util.find_spec", return_value=None):
            self.assertIsNone(school_ai_browser_command())

    def test_frozen_platform_helper_names_and_spaces(self):
        for platform, suffix in (("win32", ".exe"), ("linux", ""), ("darwin", "")):
            with self.subTest(platform=platform):
                executable = Path("/tmp/packaged app/XJTUToolBox" + suffix)
                helper = executable.parent / "SchoolAIBrowser" / f"SchoolAIBrowser{suffix}"
                with patch("app.school_ai_launcher.sys.frozen", True, create=True), \
                     patch("app.school_ai_launcher.sys.executable", str(executable)), \
                     patch("app.school_ai_launcher.sys.platform", platform), \
                     patch("app.school_ai_launcher.Path.is_file", return_value=True):
                    command = school_ai_browser_command()
                self.assertEqual(command, (str(helper), []))

    def test_frozen_missing_helper_returns_none(self):
        with patch("app.school_ai_launcher.sys.frozen", True, create=True), \
             patch("app.school_ai_launcher.Path.is_file", return_value=False):
            self.assertIsNone(school_ai_browser_command())

    def test_launch_uses_exact_subprocess_argv(self):
        page = JiaoxiaozhiInterface()
        self.addCleanup(page.close)
        with patch("app.JiaoxiaozhiInterface.school_ai_browser_command",
                   return_value=("/tmp/packaged app/SchoolAIBrowser", ["--flag", "value with spaces"])), \
             patch("app.JiaoxiaozhiInterface.subprocess.Popen") as popen, \
             patch.object(page, "success"):
            page.launch()
        popen.assert_called_once_with([
            "/tmp/packaged app/SchoolAIBrowser", "--flag", "value with spaces",
        ])

    def test_missing_helper_and_popen_failure_fall_back_to_official_url(self):
        for command, popen_error in ((None, None), (("helper", []), OSError("failed"))):
            with self.subTest(command=command):
                page = JiaoxiaozhiInterface()
                self.addCleanup(page.close)
                with patch("app.JiaoxiaozhiInterface.school_ai_browser_command", return_value=command), \
                     patch("app.JiaoxiaozhiInterface.subprocess.Popen", side_effect=popen_error), \
                     patch("app.JiaoxiaozhiInterface.QDesktopServices.openUrl", return_value=True) as open_url, \
                     patch.object(page, "info"), patch.object(page, "warn"):
                    page.launch()
                open_url.assert_called_once_with(QUrl(JIAOXIAOZHI_URL))

    def test_open_url_failure_warns_user(self):
        page = JiaoxiaozhiInterface()
        self.addCleanup(page.close)
        with patch("app.JiaoxiaozhiInterface.QDesktopServices.openUrl", return_value=False), \
             patch.object(page, "warn") as warn:
            page.open_system_browser()
        warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
