"""通过 PyObjC 接入 Sparkle 原生 UI；仅由 macOS 打包应用导入。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import objc
from Foundation import NSBundle, NSError, NSObject, NSUnderlyingErrorKey, NSUserDefaults
from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from .log import logger


def _format_sparkle_error(error: NSError) -> str:
    """展开 NSError 的诊断信息和底层错误链，并限制异常链的长度。"""
    details = []
    seen = set()
    for depth in range(8):
        if id(error) in seen:
            details.append("underlying error chain contains a cycle")
            break
        seen.add(id(error))
        user_info = dict(error.userInfo() or {})
        underlying = user_info.pop(NSUnderlyingErrorKey, None)
        details.append(
            f"error[{depth}]: domain={error.domain()!r}, code={error.code()}, "
            f"description={error.localizedDescription()!r}, "
            f"failure_reason={error.localizedFailureReason()!r}, "
            f"recovery_suggestion={error.localizedRecoverySuggestion()!r}, "
            f"user_info={user_info!r}"
        )
        if underlying is None:
            break
        if not isinstance(underlying, NSError):
            details.append(f"underlying error: {underlying!r}")
            break
        error = underlying
    else:
        details.append("underlying error chain truncated after 8 errors")
    return "\n".join(details)


class NativeUpdater(Protocol):
    """声明薄适配层使用的 Sparkle 原生接口。"""

    def canCheckForUpdates(self) -> bool:
        """返回是否可以发起新的更新检查。"""
        ...

    def automaticallyChecksForUpdates(self) -> bool:
        """读取 Sparkle 持久化的自动检查偏好。"""
        ...

    def setAutomaticallyChecksForUpdates_(self, enabled: bool) -> None:
        """修改自动检查偏好。"""
        ...

    def checkForUpdatesInBackground(self) -> None:
        """执行启动时的后台检查。"""
        ...


class NativeController(Protocol):
    """声明标准更新窗口控制器接口。"""

    def updater(self) -> NativeUpdater:
        """返回底层更新器。"""
        ...

    def startUpdater(self) -> None:
        """启动 Sparkle 的调度器。"""
        ...

    def checkForUpdates_(self, sender: object | None) -> None:
        """显示原生更新检查窗口。"""
        ...


class XJTUSparkleDelegate(NSObject):
    """将安装前的原生回调转发给 Qt 应用的状态保存流程。"""

    @objc.python_method
    def configure(self, owner: MacOSUpdater) -> None:
        """持有 Python 适配器，避免回调生命周期早于更新会话结束。"""
        self.owner = owner

    @objc.signature(b"v@:@")
    def updaterWillRelaunchApplication_(self, updater: object) -> None:
        """在 Cocoa 终止进程前保存状态并跳过托盘关闭询问。"""
        self.owner.prepare_to_relaunch()

    @objc.signature(b"v@:@@")
    def updater_didAbortWithError_(self, updater: object, error: NSError) -> None:
        """记录 Sparkle 的错误；交互式错误窗口仍由 Sparkle 展示。"""
        try:
            logger.info("Sparkle update cycle stopped:\n%s", _format_sparkle_error(error))
        except Exception:
            # 原生回调中的诊断失败不能阻止应用恢复正常关闭行为。
            logger.info("Sparkle update cycle stopped: %s (error details unavailable)", error, exc_info=True)
        finally:
            self.owner.cancel_relaunch()


class MacOSUpdater(QObject):
    """在 Qt 主线程管理一个 Sparkle 控制器及设置同步。"""

    stateChanged = pyqtSignal(bool, bool)

    def __init__(self, before_relaunch: Callable[[], None], cancel_relaunch: Callable[[], None], parent: QObject) -> None:
        """载入 framework，延迟到 Qt 事件循环中启动更新器。"""
        super().__init__(parent)
        self._assert_main_thread()
        self._before_relaunch = before_relaunch
        self._cancel_relaunch = cancel_relaunch
        bundle = NSBundle.mainBundle()
        framework = Path(str(bundle.bundlePath())) / "Contents/Frameworks/Sparkle.framework"
        objc.loadBundle("Sparkle", {}, bundle_path=str(framework))
        self._delegate = XJTUSparkleDelegate.alloc().init()
        self._delegate.configure(self)
        controller_class = objc.lookUpClass("SPUStandardUpdaterController")
        self._controller = cast(NativeController, controller_class.alloc().initWithStartingUpdater_updaterDelegate_userDriverDelegate_(
            False, self._delegate, None,
        ))
        self._updater = self._controller.updater()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh_state)
        self._last_state: tuple[bool, bool] | None = None

    @staticmethod
    def _assert_main_thread() -> None:
        """阻止在后台线程调用 Cocoa/Sparkle。"""
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Sparkle must be used on the GUI main thread")

    def start(self, previous_auto_check: bool) -> None:
        """只首次迁移旧设置，以后以 Sparkle 持久化偏好为准。"""
        self._assert_main_thread()
        defaults = NSUserDefaults.standardUserDefaults()
        if not defaults.boolForKey_("XJTUSparklePreferencesMigrated"):
            self._updater.setAutomaticallyChecksForUpdates_(previous_auto_check)
            defaults.setBool_forKey_(True, "XJTUSparklePreferencesMigrated")
        self._controller.startUpdater()
        if self._updater.automaticallyChecksForUpdates():
            self._updater.checkForUpdatesInBackground()
        self._timer.start()
        self._refresh_state()

    def check_for_updates(self) -> None:
        """在允许检查时打开原生窗口，避免重复会话。"""
        self._assert_main_thread()
        if self._updater.canCheckForUpdates():
            self._controller.checkForUpdates_(None)
            self._refresh_state()

    def set_automatic_checks(self, enabled: bool) -> None:
        """处理用户明确改变自动检查开关的操作。"""
        self._assert_main_thread()
        self._updater.setAutomaticallyChecksForUpdates_(enabled)
        self._refresh_state()

    def _refresh_state(self) -> None:
        """同步原生窗口更改的偏好和按钮状态，不重置更新调度周期。"""
        state = (bool(self._updater.canCheckForUpdates()), bool(self._updater.automaticallyChecksForUpdates()))
        if state != self._last_state:
            self._last_state = state
            self.stateChanged.emit(*state)

    def prepare_to_relaunch(self) -> None:
        """在进程真正退出前完成必要的同步保存。"""
        self._before_relaunch()

    def cancel_relaunch(self) -> None:
        """更新失败时恢复正常窗口关闭行为。"""
        self._cancel_relaunch()
