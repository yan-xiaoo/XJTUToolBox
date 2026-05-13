from __future__ import annotations

import queue
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
import requests

from app.utils.qrcode_login import (
    QRCodeLoginAction,
    QRCodeLoginActionType,
    QRCodeLoginCancelledError,
    QRCodeLoginProvider,
    QRCodeLoginRequest,
    QRCodeLoginResult,
)
from auth.new_qrcode_login import QRCodeLoginMixin, QRCodeLoginStatus


class QtQRCodeLoginProvider(QObject):
    """
    通过 Qt 信号把业务线程中的二维码登录请求转交给主线程对话框处理。
    """
    requestQRCode = pyqtSignal(object)
    imageReady = pyqtSignal(object, object)
    statusChanged = pyqtSignal(object, str)
    finished = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        """
        创建 Qt 二维码登录交互提供者。
        """
        super().__init__(parent)
        self._dialog_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_queue: queue.Queue[QRCodeLoginAction] | None = None
        self._active_request: QRCodeLoginRequest | None = None

    def handle(self, login_util: QRCodeLoginMixin, request: QRCodeLoginRequest) -> QRCodeLoginResult:
        """
        显示二维码登录对话框，并在当前业务线程中轮询扫码状态。
        """
        with self._dialog_lock:
            action_queue: queue.Queue[QRCodeLoginAction] = queue.Queue()
            with self._state_lock:
                self._active_queue = action_queue
                self._active_request = request

            self.requestQRCode.emit(request)
            polling_enabled = False
            completed = False
            try:
                self._refresh_qrcode(login_util, request)
                polling_enabled = True
                while True:
                    action = self._take_action(action_queue)
                    if action is not None:
                        if action.type == QRCodeLoginActionType.CANCEL:
                            raise QRCodeLoginCancelledError("已取消二维码登录。")
                        if action.type == QRCodeLoginActionType.REFRESH:
                            self._refresh_qrcode(login_util, request)
                            polling_enabled = True

                    if polling_enabled:
                        try:
                            result = login_util.poll_qrcode_status()
                        except requests.Timeout:
                            self.statusChanged.emit(request, "二维码状态检查超时，正在重试。")
                            self._sleep_or_handle_cancel(action_queue)
                            continue
                        except requests.RequestException:
                            self.statusChanged.emit(request, "二维码状态检查失败，请刷新二维码。")
                            polling_enabled = False
                            self._sleep_or_handle_cancel(action_queue)
                            continue
                        self.statusChanged.emit(request, result.message)
                        if result.status == QRCodeLoginStatus.AUTHORIZED:
                            completed = True
                            self.finished.emit(request)
                            return QRCodeLoginResult(result.user_id, result.state_key)
                        if result.status in (
                                QRCodeLoginStatus.CANCELLED,
                                QRCodeLoginStatus.EXPIRED,
                                QRCodeLoginStatus.ERROR):
                            polling_enabled = False

                    self._sleep_or_handle_cancel(action_queue)
            finally:
                if not completed:
                    self.finished.emit(request)
                with self._state_lock:
                    if self._active_queue is action_queue:
                        self._active_queue = None
                        self._active_request = None

    @pyqtSlot(object)
    def submit_action(self, action: QRCodeLoginAction) -> None:
        """
        接收主线程 UI 提交的二维码登录用户动作。
        """
        with self._state_lock:
            action_queue = self._active_queue
        if action_queue is not None:
            action_queue.put(action)

    def _refresh_qrcode(self, login_util: QRCodeLoginMixin, request: QRCodeLoginRequest) -> None:
        """
        请求新的二维码图片并发送给 UI。
        """
        image = login_util.get_qrcode_image()
        self.imageReady.emit(request, image)
        self.statusChanged.emit(request, "请使用手机 App 扫码登录。")

    def _take_action(self, action_queue: queue.Queue[QRCodeLoginAction]) -> QRCodeLoginAction | None:
        """
        非阻塞地取出一个 UI 动作。
        """
        try:
            return action_queue.get_nowait()
        except queue.Empty:
            return None

    def _sleep_or_handle_cancel(self, action_queue: queue.Queue[QRCodeLoginAction]) -> None:
        """
        在两次轮询之间短暂等待，同时及时响应取消动作。
        """
        deadline = time.time() + 2.0
        while time.time() < deadline:
            action = self._take_action(action_queue)
            if action is not None:
                action_queue.put(action)
                return
            time.sleep(0.1)
