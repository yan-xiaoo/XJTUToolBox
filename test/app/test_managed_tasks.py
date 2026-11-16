import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import psutil
from schedule.calendar_process import run_child, CalendarJobCancelled

TEST_DOMAIN = 'qt-ui'
TEST_REGRESSION = True


class ManagedProcessTest(unittest.TestCase):
    def test_qt_plugin_bootstrap_starts_native_platform_in_unicode_environment(self):
        if sys.platform != 'win32':
            self.skipTest('Windows Unicode plugin-path regression')
        code = '''
import os, ctypes
ctypes.windll.kernel32.SetErrorMode(3)
os.environ['QT_QPA_PLATFORM'] = 'windows'
from app.qt_bootstrap import configure_qt_plugins
configure_qt_plugins()
from PyQt5.QtWidgets import QApplication
app = QApplication([])
assert app.platformName() == 'windows'
app.quit()
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True,
                                timeout=15, cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cancel_before_spawn(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CalendarJobCancelled):
            run_child(['not-a-real-command'], env=os.environ.copy(), cancel=cancel)

    def test_timeout_kills_descendant_process(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            code = ('import subprocess,sys,time,pathlib; '
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
                    f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)')
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_child([sys.executable, '-c', code], env=os.environ.copy(),
                              cancel=threading.Event(), timeout=2)
                self.assertTrue(pidfile.exists(), 'child never started')
                pid = int(pidfile.read_text())
                try:
                    psutil.Process(pid).wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
            finally:
                if pidfile.exists() and psutil.pid_exists(int(pidfile.read_text())):
                    psutil.Process(int(pidfile.read_text())).kill()

    def test_qt_exit_and_parent_destruction_cancel_running_jobs(self):
        # Isolate Qt teardown: a regression must fail this child, not crash the suite.
        code = '''
import os, pathlib, threading
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import PyQt5
from PyQt5.QtCore import QCoreApplication, QTimer
QCoreApplication.setLibraryPaths([str(pathlib.Path(PyQt5.__file__).parent/'Qt5'/'plugins')])
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5 import sip
from app.threads.ManagedTaskThread import ManagedTaskThread
app = QApplication([])
class Job(ManagedTaskThread):
    def run(self):
        self._cancel.wait(30)
parent = QWidget()
first = Job(parent)
first.start()
sip.delete(parent)
assert first.wait(2000), 'parent destruction did not cancel'
second = Job()
second.start()
QTimer.singleShot(50, app.quit)
app.exec_()
assert not second.isRunning(), 'quit left a running QThread'
assert not ManagedTaskThread._active_jobs, 'registry retained jobs'
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True,
                                timeout=15, cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
