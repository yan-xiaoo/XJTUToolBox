"""Graceful terminal interrupt support for the Qt event loop."""

from __future__ import annotations

import signal
from dataclasses import dataclass
from types import FrameType
from typing import Callable

from PyQt5.QtCore import QTimer


SignalHandler = int | Callable[[int, FrameType | None], object] | None


@dataclass
class CtrlCController:
    """Own the wake-up timer and make repeated interrupts idempotent."""

    application: object
    timer: QTimer
    previous_handler: SignalHandler
    shutdown_requested: bool = False

    def handle(self, _signal_number: int, _frame: FrameType | None) -> None:
        if self.shutdown_requested:
            return
        self.shutdown_requested = True
        self.application.quit()

    def restore(self) -> None:
        """Restore process-global signal state, mainly for embedders and tests."""

        self.timer.stop()
        signal.signal(signal.SIGINT, self.previous_handler)


def install_ctrl_c_handler(application: object, *, interval_ms: int = 150) -> CtrlCController | None:
    """Make Ctrl+C quit a Qt application cleanly.

    CPython only runs signal handlers while it owns the interpreter.  A quiet
    Qt event loop can remain inside C++ indefinitely, so a small timer returns
    control to Python often enough to dispatch SIGINT.  Signal installation is
    only legal on the main thread; embedders that call this elsewhere receive
    ``None`` instead of a startup failure.
    """

    if interval_ms <= 0:
        raise ValueError("Ctrl+C wake-up interval must be positive")

    try:
        previous_handler = signal.getsignal(signal.SIGINT)
        timer = QTimer(application)
        timer.setInterval(interval_ms)
        timer.timeout.connect(lambda: None)
        controller = CtrlCController(application, timer, previous_handler)
        signal.signal(signal.SIGINT, controller.handle)
    except (AttributeError, ValueError):
        return None

    timer.start()
    return controller
