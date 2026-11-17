import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

import build
from app import qt_bootstrap

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True


class QtPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="中文路径-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "PyQt5"
        self.plugins = self.root / "Qt5" / "plugins"
        (self.plugins / "platforms").mkdir(parents=True)

    def test_runtime_prefers_existing_wheel_plugins_and_preserves_other_paths(self):
        core = Mock()
        core.libraryPaths.return_value = ["other", str(self.plugins)]
        with patch.object(qt_bootstrap, "sys", SimpleNamespace(platform="win32")), \
             patch.object(qt_bootstrap.PyQt5, "__file__", str(self.root / "__init__.py")), \
             patch.object(qt_bootstrap, "QCoreApplication", core):
            qt_bootstrap.configure_qt_plugins()
        core.setLibraryPaths.assert_called_once_with([str(self.plugins), "other"])

    def test_runtime_leaves_non_windows_unchanged(self):
        with patch.object(qt_bootstrap, "sys", SimpleNamespace(platform="linux")), \
             patch.object(qt_bootstrap, "QCoreApplication") as core:
            qt_bootstrap.configure_qt_plugins()
        core.setLibraryPaths.assert_not_called()

    def test_runtime_leaves_custom_installation_unchanged(self):
        with patch.object(qt_bootstrap, "sys", SimpleNamespace(platform="win32")), \
             patch.object(qt_bootstrap.PyQt5, "__file__", str(self.root / "other" / "__init__.py")), \
             patch.object(qt_bootstrap, "QCoreApplication") as core:
            qt_bootstrap.configure_qt_plugins()
        core.setLibraryPaths.assert_not_called()

    def test_build_repairs_only_paths_under_broken_prefix(self):
        info = SimpleNamespace(location={"PrefixPath": "C:/broken-qt",
            "PluginsPath": "C:/broken-qt/plugins", "BinariesPath": "C:/broken-qt/bin",
            "OtherPath": "C:/external"}, qt_inside_package=False, qt_lib_dir=None)
        with patch.object(build, "sys", SimpleNamespace(platform="win32")), \
             patch("PyQt5.__file__", str(self.root / "__init__.py")), \
             patch("PyInstaller.utils.hooks.qt.pyqt5_library_info", info):
            build.configure_windows_qt_paths()
        self.assertEqual(Path(info.location["PluginsPath"]), self.plugins)
        self.assertEqual(info.location["OtherPath"], "C:/external")
        self.assertEqual(info.qt_lib_dir, self.root / "Qt5" / "bin")
        self.assertTrue(info.qt_inside_package)

    def test_build_leaves_working_paths_unchanged(self):
        info = SimpleNamespace(location={"PrefixPath": "custom", "PluginsPath": str(self.plugins)})
        with patch.object(build, "sys", SimpleNamespace(platform="win32")), \
             patch("PyQt5.__file__", str(self.root / "__init__.py")), \
             patch("PyInstaller.utils.hooks.qt.pyqt5_library_info", info):
            build.configure_windows_qt_paths()
        self.assertEqual(info.location["PrefixPath"], "custom")

    def test_build_does_not_patch_non_windows(self):
        with patch.object(build, "sys", SimpleNamespace(platform="darwin")), \
             patch("PyInstaller.utils.hooks.qt.pyqt5_library_info") as info:
            build.configure_windows_qt_paths()
        self.assertEqual(info.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
