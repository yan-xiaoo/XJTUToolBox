import os
import threading
import unittest
from unittest.mock import patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_STATE_HOME", "/tmp/xjtu-test-state")
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/xjtu-test-config")

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtWidgets import QApplication, QWidget

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

from qfluentwidgets import InfoBarPosition

from app.components.ProgressInfoBar import ProgressBarThread, ProgressInfoBar

APP = QApplication.instance() or QApplication([])


class SilentExitThread(ProgressBarThread):
    """run() 不发任何结束信号：模拟异常/静默退出；release 存在时先挂起。"""

    def __init__(self, release=None):
        super().__init__()
        self.entered = threading.Event()
        self.release = release

    def run(self):
        self.entered.set()
        if self.release is not None:
            self.release.wait(5)


class FinishingThread(ProgressBarThread):
    """正常结束：发 hasFinished 后返回。用于验证旧线程的 hasFinished 被断开。"""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self):
        self.entered.set()
        self.release.wait(5)
        self.hasFinished.emit()


class CancelingThread(ProgressBarThread):
    """主动取消：发 canceled 后返回。用于验证旧线程已入队的取消信号被丢弃。"""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self):
        self.entered.set()
        self.release.wait(5)
        self.canceled.emit()


class ChattyThread(ProgressBarThread):
    """一次性发出全部状态类信号后返回，用于验证旧任务的 UI 事件不污染新任务。"""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self):
        self.entered.set()
        self.release.wait(5)
        self.titleChanged.emit("旧标题")
        self.messageChanged.emit("旧内容")
        self.progressChanged.emit(99)
        self.maximumChanged.emit(123)
        self.deadTime.emit(99)
        self.progressPaused.emit(True)


class ProgressInfoBarTest(unittest.TestCase):
    def make_bar(self, thread):
        bar = ProgressInfoBar("标题", "内容", position=InfoBarPosition.NONE)
        events = []
        bar.canceled.connect(lambda: events.append("canceled"))
        bar.finished.connect(lambda: events.append("finished"))
        bar.connectToThread(thread)
        self.addCleanup(self._teardown, bar, thread)
        return bar, events

    @staticmethod
    def _teardown(bar, *threads):
        # bar.thread_ 一并纳入：重绑定用例里 make_bar 只传了旧线程，
        # 保证退出后才释放引用。
        targets = [t for t in dict.fromkeys((*threads, bar.thread_)) if t is not None]
        for thread in targets:
            release = getattr(thread, "release", None)
            if release is not None:
                release.set()
        for thread in targets:
            if thread.isRunning():
                thread.quit()
                thread.wait(5000)
        try:
            bar.timer.stop()
            bar.close()
        except RuntimeError:
            pass  # close() -> deleteLater() 已销毁对象

    def assertTimerStopped(self, bar):
        try:
            active = bar.timer.isActive()
        except RuntimeError:
            active = False  # 对象已销毁，定时器必然不存在
        self.assertFalse(active)

    def wait_entered(self, thread):  # 保证 started 已入队后再 processEvents
        self.assertTrue(thread.entered.wait(5))

    # 原实现这里 events == []
    def test_silent_exit_reports_canceled_exactly_once(self):
        thread = SilentExitThread()
        bar, events = self.make_bar(thread)

        thread.start()
        self.assertTrue(thread.wait(5000))
        with patch("app.components.ProgressInfoBar.logger") as logger:
            APP.processEvents()

        self.assertEqual(events, ["canceled"])
        self.assertTrue(bar._saw_end)
        self.assertTimerStopped(bar)
        logger.warning.assert_called_once()
        self.assertIn("线程未发送结束信号", logger.warning.call_args[0][0])

    # 成功路径不变：只有 finished，且不会记录 warning
    def test_normal_finish_reports_finished_without_warning(self):
        thread = FinishingThread()
        thread.release.set()
        bar, events = self.make_bar(thread)

        thread.start()
        self.assertTrue(thread.wait(5000))
        with patch("app.components.ProgressInfoBar.logger") as logger:
            APP.processEvents()

        self.assertEqual(events, ["finished"])
        self.assertTrue(bar._saw_end)
        logger.warning.assert_not_called()

    # 结束判定不许放回 checkProcess
    def test_polling_does_not_decide_end_while_signals_pending(self):
        thread = FinishingThread()  # 先 clear，让 worker 挂在 run 里
        bar, events = self.make_bar(thread)

        thread.start()
        self.wait_entered(thread)
        APP.processEvents()  # 派发 started -> 定时器真的在跑
        self.assertTrue(bar.timer.isActive())

        thread.release.set()  # 线程退出，但结束信号仍在队列里
        self.assertTrue(thread.wait(5000))

        with patch("app.components.ProgressInfoBar.logger") as logger:
            bar.checkProcess()  # 轮询不得自行判定结束
        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertTimerStopped(bar)
        logger.warning.assert_not_called()

        APP.processEvents()  # hasFinished 先于 QThread.finished 派发
        self.assertEqual(events, ["finished"])
        self.assertTrue(bar._saw_end)

    # 点关闭后线程静默退出；重复 onThreadExited 不重复发
    def test_close_click_then_silent_exit_reports_once(self):
        release = threading.Event()
        thread = SilentExitThread(release)
        bar, events = self.make_bar(thread)

        thread.start()
        self.wait_entered(thread)
        APP.processEvents()
        bar.onCloseButtonClicked()  # stopped=True，closedSignal -> onStopSignal

        release.set()
        self.assertTrue(thread.wait(5000))
        APP.processEvents()
        self.assertEqual(events, ["canceled"])

        bar.onThreadExited()  # 二次调用（此时 sender() 为 None）
        bar.onThreadExited()
        self.assertEqual(events, ["canceled"])

    # 旧线程的任何信号都不再影响组件
    def test_rebinding_disconnects_old_thread(self):
        old = FinishingThread()  # 会发 hasFinished，才能覆盖断开缺口
        current = FinishingThread()
        bar, events = self.make_bar(old)
        bar.connectToThread(
            current
        )  # 不修（progressPause → progressPaused）的话这里 AttributeError

        old.release.set()
        old.start()
        self.assertTrue(old.wait(5000))
        APP.processEvents()

        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertFalse(bar.timer.isActive())
        self.assertIs(bar.thread_, current)

    # 旧线程已发出 hasFinished 且事件已入队，派发前重绑定：旧信号必须被丢弃。
    # 注意：本机 PyQt5 在 disconnect（生产默认 disconnect_last=True）时会连代理的排队
    # 事件一起清掉，这条测试锁定该默认语义下的最终行为；「保留旧连接、事件已入队」的
    # 绑定校验路径由 test_queued_finish_before_rebind_with_live_connection_is_dropped 覆盖。
    def test_rebinding_ignores_queued_finish_from_old_thread(self):
        old = FinishingThread()
        current = FinishingThread()
        bar, events = self.make_bar(old)

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        old.release.set()
        self.assertTrue(old.wait(5000))  # hasFinished 已入队，仍未派发

        bar.connectToThread(current)  # 抢在事件派发前重绑定
        APP.processEvents()

        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)
        self.assertTrue(
            current.can_run
        )  # 若旧信号触发 close，会经 closedSignal 停掉新线程

    # 旧线程已发出 canceled 且事件已入队，派发前重绑定：旧信号必须被丢弃
    def test_rebinding_ignores_queued_cancel_from_old_thread(self):
        old = CancelingThread()
        current = CancelingThread()
        bar, events = self.make_bar(old)

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        old.release.set()
        self.assertTrue(old.wait(5000))  # canceled 已入队，仍未派发

        bar.connectToThread(current)  # 抢在事件派发前重绑定
        APP.processEvents()

        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)
        self.assertTrue(
            current.can_run
        )  # 若旧信号触发 close，会经 closedSignal 停掉新线程

    # 旧线程的 started 已入队，派发前重绑定：不得重置新任务状态或启动计时器
    def test_rebinding_ignores_queued_start_from_old_thread(self):
        old = SilentExitThread(threading.Event())  # 线程挂住，保证 started 仍在队列中
        current = SilentExitThread()
        bar, _ = self.make_bar(old)

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        bar.connectToThread(current)  # 抢在事件派发前重绑定

        bar.stopped = True
        bar._saw_end = True
        APP.processEvents()

        self.assertTrue(bar.stopped)
        self.assertTrue(bar._saw_end)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)

    # 旧线程的进度/文案等事件已入队，派发前重绑定：不得污染新任务的 UI 与超时参数
    def test_rebinding_ignores_queued_ui_events_from_old_thread(self):
        old = ChattyThread()
        current = ChattyThread()
        bar, _ = self.make_bar(old)

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        old.release.set()
        self.assertTrue(old.wait(5000))  # 全部 UI 事件已入队，仍未派发

        bar.connectToThread(current)  # 抢在事件派发前重绑定
        APP.processEvents()

        self.assertEqual(bar.titleLabel.text(), "标题")
        self.assertEqual(bar.contentLabel.text(), "内容")
        self.assertEqual(bar.progressBar.value(), 0)
        self.assertFalse(bar.progressBar.isPaused())
        self.assertEqual(bar.thread_dead_time, 5)
        self.assertIs(bar.thread_, current)

    # 绑定校验本身：旧线程绑定的接收器即便被派发，也必须丢弃事件
    def test_stale_binding_receiver_drops_events(self):
        old = FinishingThread()
        current = FinishingThread()
        bar, events = self.make_bar(old)
        stale_receivers = list(bar._thread_receivers)  # 旧线程的全部绑定

        bar.connectToThread(current)  # 重绑定后旧接收器全部失效

        for _signal, receiver in stale_receivers:
            receiver()  # 模拟已入队事件在重绑定后才派发到旧接收器

        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)

    # 真实 Qt 排队路径：连接仍在、绑定已切走时，旧接收器必须丢弃事件
    def test_queued_signal_from_unbound_thread_is_dropped(self):
        old = FinishingThread()
        current = FinishingThread()
        bar, events = self.make_bar(old)

        bar.connectToThread(current, disconnect_last=False)  # 保留旧连接，仅切换绑定

        old.start()
        self.wait_entered(old)
        old.release.set()
        self.assertTrue(old.wait(5000))
        APP.processEvents()  # 旧线程的 started/hasFinished/finished 经真实 queued 连接派发

        self.assertEqual(events, [])
        self.assertFalse(bar._saw_end)
        self.assertIs(bar.thread_, current)
        self.assertTrue(
            current.can_run
        )  # 旧信号若触发 close，会经 closedSignal 停掉新线程

    # 真实排队路径补强：旧线程先发出并等待入队 -> 重绑定（保留旧连接）-> 才派发。
    # 用 disconnect_last=False 隔离 PyQt「disconnect 清排队事件」语义，确保事件真的被
    # 派发到旧接收器、由绑定校验丢弃；金丝雀断言证明事件确实经过派发，测试非空跑。
    def test_queued_finish_before_rebind_with_live_connection_is_dropped(self):
        old = FinishingThread()
        current = FinishingThread()
        bar, events = self.make_bar(old)
        delivered = []
        old.hasFinished.connect(lambda: delivered.append("old"))  # 金丝雀：独立于组件绑定

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        old.release.set()
        self.assertTrue(old.wait(5000))  # hasFinished/finished 已入队，仍未派发

        bar.connectToThread(current, disconnect_last=False)  # 保留旧连接，仅切换绑定
        # 重绑定会重置这些状态，哨兵必须在重绑定之后设置
        bar.stopped = True
        bar._saw_end = True
        APP.processEvents()

        self.assertEqual(delivered, ["old"])  # 事件确实被派发过，测试非空跑
        self.assertEqual(events, [])
        self.assertTrue(bar.stopped)  # onThreadStart 不得重置新任务状态
        self.assertTrue(bar._saw_end)
        self.assertFalse(bar._closed)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)
        self.assertTrue(
            current.can_run
        )  # 若旧信号触发 close，会经 closedSignal 停掉新线程

    # cancel 孪生：旧线程先发出 canceled 并等待入队 -> 重绑定（保留旧连接）-> 才派发。
    def test_queued_cancel_before_rebind_with_live_connection_is_dropped(self):
        old = CancelingThread()
        current = CancelingThread()
        bar, events = self.make_bar(old)
        delivered = []
        old.canceled.connect(lambda: delivered.append("old"))  # 金丝雀：独立于组件绑定

        old.start()
        self.wait_entered(old)  # started 已入队，不派发
        old.release.set()
        self.assertTrue(old.wait(5000))  # canceled/finished 已入队，仍未派发

        bar.connectToThread(current, disconnect_last=False)  # 保留旧连接，仅切换绑定
        # 重绑定会重置这些状态，哨兵必须在重绑定之后设置
        bar.stopped = True
        bar._saw_end = True
        APP.processEvents()

        self.assertEqual(delivered, ["old"])  # 事件确实被派发过，测试非空跑
        self.assertEqual(events, [])
        self.assertTrue(bar.stopped)  # onThreadStart 不得重置新任务状态
        self.assertTrue(bar._saw_end)
        self.assertFalse(bar._closed)
        self.assertTimerStopped(bar)
        self.assertIs(bar.thread_, current)
        self.assertTrue(
            current.can_run
        )  # 若旧信号触发 close，会经 closedSignal 停掉新线程

    # 关闭/销毁后，旧线程信号不得再进入闭包访问已删除的 C++ 对象（P2 崩溃路径）
    def test_closed_bar_drops_late_thread_signals(self):
        release = threading.Event()
        thread = SilentExitThread(release)
        bar, events = self.make_bar(thread)
        thread.start()
        self.wait_entered(thread)
        APP.processEvents()

        bar.close()  # 关闭即显式断开全部接收器连接并让绑定失效
        self.assertEqual(bar._thread_receivers, [])  # 关闭时已断开并清空
        thread.deadTime.emit(42)  # 该槽不碰 C++ 对象，可直接观察是否被污染
        APP.processEvents()
        self.assertEqual(bar.thread_dead_time, 5)
        self.assertTrue(bar._closed)

        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(bar))  # 延迟删除已生效

        # 修复前：闭包访问已销毁的 QLabel/QTimer 会抛 RuntimeError 并触发 PyQt abort。
        # 上面的断言已保证失效生效，这里只验证真实信号路径静默丢弃、不崩溃。
        thread.titleChanged.emit("迟到标题")
        thread.progressChanged.emit(88)
        thread.hasFinished.emit()
        APP.processEvents()
        self.assertEqual(events, [])

    # 父控件直接销毁（不经过 closeEvent）后，迟到信号也必须被丢弃；destroyed 自清理
    # 挂钩（不接回自身方法）负责断开连接并释放包装对象，sip.isdeleted 仍在派发时判活兜底
    def test_parent_destroyed_bar_drops_late_thread_signals(self):
        release = threading.Event()
        thread = SilentExitThread(release)
        parent = QWidget()
        bar = ProgressInfoBar(
            "标题", "内容", position=InfoBarPosition.NONE, parent=parent
        )
        events = []
        bar.canceled.connect(lambda: events.append("canceled"))
        bar.finished.connect(lambda: events.append("finished"))
        bar.connectToThread(thread)
        self.addCleanup(self._teardown, bar, thread)

        thread.start()
        self.wait_entered(thread)
        APP.processEvents()

        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(parent))
        self.assertTrue(sip.isdeleted(bar))  # 父销毁会连同子控件一起销毁
        self.assertEqual(bar._thread_receivers, [])  # destroyed 自清理已断开并清空

        thread.deadTime.emit(42)  # 该槽不碰 C++ 对象，修复前会污染状态且失败干净
        self.assertEqual(bar.thread_dead_time, 5)

        # 修复前：闭包访问已销毁的 QLabel/QTimer 会抛 RuntimeError 并触发 PyQt abort
        thread.titleChanged.emit("迟到标题")
        thread.hasFinished.emit()
        APP.processEvents()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
