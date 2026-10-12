import os
import threading
import time
import unittest

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_STATE_HOME", "/tmp/xjtu-test-state")
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/xjtu-test-config")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.threads.ProcessWidget import ProcessThread, ProcessWidget

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

APP = QApplication.instance() or QApplication([])


class ProcessWidgetTestBase(unittest.TestCase):
    """ProcessWidget 测试公共基类：统一负责 widget/thread 的创建与清理。"""

    def _teardown(self, widget, thread):
        """清理期间同时持有 widget 和 thread，防止 GC 先删掉子 QTimer。"""
        widget.timer.stop()
        if thread.isRunning():
            thread.quit()
            thread.wait(5000)
        widget.close()

    def make_process_widget(self, thread, stoppable=True, hide_on_end=True):
        widget = ProcessWidget(thread, stoppable=stoppable, hide_on_end=hide_on_end)
        # 绑定方法持有 self，参数持有 widget/thread，保证清理执行期间对象存活
        self.addCleanup(self._teardown, widget, thread)
        return widget


class SilentExitThread(ProcessThread):
    """模拟线程异常退出：run() 直接返回，不发任何结束信号。"""

    def run(self):
        return


class ProcessWidgetSilentExitTest(ProcessWidgetTestBase):
    def make_widget(self):
        thread = SilentExitThread()
        widget = self.make_process_widget(thread, stoppable=True, hide_on_end=True)
        canceled, finished = [], []
        widget.canceled.connect(lambda: canceled.append(True))
        widget.finished.connect(lambda: finished.append(True))
        return widget, thread, canceled, finished

    def test_silent_exit_reports_and_stops_timer(self):
        widget, thread, canceled, finished = self.make_widget()
        thread.start()
        self.assertTrue(thread.wait(5000))
        APP.processEvents()  # 交付 started 与 QThread.finished

        self.assertEqual(canceled, [True])
        self.assertEqual(finished, [])
        self.assertFalse(widget.timer.isActive())

        widget.checkProcess()  # 再检查也不重复上报
        self.assertEqual(canceled, [True])

    def test_has_finished_does_not_report_canceled(self):
        widget, thread, canceled, finished = self.make_widget()
        widget.onThreadStart()
        thread.hasFinished.emit()  # 同线程直连 -> onFinished
        widget.onThreadExited()  # 模拟 QThread.finished
        self.assertEqual(finished, [True])
        self.assertEqual(canceled, [])
        self.assertFalse(widget.timer.isActive())

    def test_thread_canceled_is_reported_once(self):
        widget, thread, canceled, finished = self.make_widget()
        widget.onThreadStart()
        thread.canceled.emit()  # 同线程直连 -> onStopped
        widget.onThreadExited()
        self.assertEqual(canceled, [True])
        self.assertEqual(finished, [])

    def test_user_cancel_path_still_reports_once(self):
        widget, _, canceled, _ = self.make_widget()
        widget.onThreadStart()
        widget.onCancelButtonClicked()
        widget.onThreadExited()
        self.assertEqual(len(canceled), 1)
        widget.onThreadExited()
        self.assertEqual(len(canceled), 1)


class HasFinishedThread(ProcessThread):
    """release 被 set 后才发 hasFinished 并退出。"""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def run(self):
        self.release.wait(5)
        self.hasFinished.emit()


class ProcessWidgetFinishRaceTest(ProcessWidgetTestBase):
    def test_check_process_does_not_race_queued_finish(self):
        thread = HasFinishedThread()
        widget = self.make_process_widget(thread, stoppable=True, hide_on_end=False)

        canceled, finished = [], []
        widget.canceled.connect(lambda: canceled.append(True))
        widget.finished.connect(lambda: finished.append(True))

        thread.start()
        deadline = time.time() + 5
        while not widget.timer.isActive() and time.time() < deadline:
            APP.processEvents()  # 等 started 送达，启动监控定时器

        thread.release.set()
        self.assertTrue(thread.wait(5000))
        # hasFinished 与 QThread.finished 均已从 worker 发出，但还没派发到主线程
        widget.checkProcess()  # 若按 isRunning() 轮询判断，会误判为异常退出并补发 canceled
        self.assertEqual(canceled, [])

        APP.processEvents()  # 派发排队的结束信号
        self.assertEqual(canceled, [])
        self.assertEqual(finished, [True])
        self.assertFalse(widget.timer.isActive())


if __name__ == "__main__":
    unittest.main()
