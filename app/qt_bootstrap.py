"""Resolve bundled Qt plugins with Python's Unicode-aware filesystem paths."""
from pathlib import Path
import sys
import os
import PyQt5
from PyQt5.QtCore import QCoreApplication


def configure_qt_plugins():
    if sys.platform != 'win32':
        return
    # Qt 5.15.2 on Windows can misdecode the default path in a Unicode venv.
    # This also works in PyInstaller's PyQt5/Qt5 layout. Keep other plugin
    # directories for optional Qt modules, after the matching packaged build.
    plugins = Path(PyQt5.__file__).resolve().parent / 'Qt5' / 'plugins'
    if (plugins / 'platforms').is_dir():
        paths = [path for path in QCoreApplication.libraryPaths()
                 if os.path.normcase(os.path.normpath(path)) != os.path.normcase(str(plugins))]
        QCoreApplication.setLibraryPaths([str(plugins), *paths])
