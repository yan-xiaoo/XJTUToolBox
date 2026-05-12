from __future__ import annotations

import queue
import threading

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from app.utils.mfa import MFAAction, MFAActionType, MFACancelledError, MFARequest
from auth.new_login import NewLogin


class QtMFAProvider(QObject):
    """
    通过 Qt 信号把业务线程中的 MFA 请求转交给主线程对话框处理。
    """
    # 在开始处理请求时，发送 MFARequest 对象。
    requestMFA = pyqtSignal(object)
    # 在发送验证码后，返回服务端给出的验证码发送情况。格式为 (MFARequest, success: bool, message: str)
    sendResult = pyqtSignal(object, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """
        创建 Qt MFA 交互提供者。
        """
        super().__init__(parent)
        # 同时只能显示一个请求两步验证的对话框
        self._dialog_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_queue: queue.Queue[MFAAction] | None = None
        self._active_request: MFARequest | None = None

    def handle(self, context: NewLogin.MFAContext, request: MFARequest) -> bool:
        """
        显示 MFA 对话框，并在当前业务线程中处理发送验证码与验证验证码。
        """
        with self._dialog_lock:
            action_queue: queue.Queue[MFAAction] = queue.Queue()
            with self._state_lock:
                self._active_queue = action_queue
                self._active_request = request

            self.requestMFA.emit(request)
            try:
                while True:
                    action = action_queue.get()
                    if action.type == MFAActionType.CANCEL:
                        raise MFACancelledError("已取消安全验证。")

                    if action.type == MFAActionType.SEND_CODE:
                        self._send_code(context, request)
                        continue

                    if action.type == MFAActionType.VERIFY_CODE:
                        context.verify_phone_code(action.code)
                        return action.trust_agent
            finally:
                with self._state_lock:
                    if self._active_queue is action_queue:
                        self._active_queue = None
                        self._active_request = None

    def report_send_result(self, request: MFARequest, success: bool, message: str = "") -> None:
        """
        向主线程报告验证码发送结果。
        """
        self.sendResult.emit(request, success, message)

    @pyqtSlot(object)
    def submit_action(self, action: MFAAction) -> None:
        """
        接收主线程 UI 提交的 MFA 用户动作。
        """
        with self._state_lock:
            action_queue = self._active_queue
        if action_queue is not None:
            action_queue.put(action)

    def _send_code(self, context: NewLogin.MFAContext, request: MFARequest) -> None:
        """
        在业务线程中发送验证码，并把结果反馈给 UI。
        """
        try:
            context.send_verify_code()
        except Exception as exc:
            self.report_send_result(request, False, str(exc))
        else:
            self.report_send_result(request, True, "")
