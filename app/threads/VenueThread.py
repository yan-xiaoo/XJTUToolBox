"""体育场馆查询线程 - 完全仿照 LMSThread 模式。"""

from __future__ import annotations

import logging
from enum import Enum

from PyQt5.QtCore import pyqtSignal

from app.venues.venue import VenueUtil, VenueAPIError
from app.threads.ProcessWidget import ProcessThread
from app.utils import accounts

from captcha_solver import fetch_captcha, detect_gap, gen_track, build_yzm

_log = logging.getLogger("default")


class VenueAction(Enum):
    LOAD_VENUES = "venues"
    LOAD_SLOTS = "slots"
    BOOK = "book"
    LOAD_ORDERS = "orders"
    CANCEL_ORDER = "cancel_order"


class VenueThread(ProcessThread):
    """体育场馆后台线程（登录 + 查询 + 预订）。"""

    venuesLoaded = pyqtSignal(list)    # list[VenueInfo]
    slotsLoaded = pyqtSignal(list, list)  # (ok_slots, locked_slots)
    ordersLoaded = pyqtSignal(list)    # list[OrderInfo]
    orderCanceled = pyqtSignal(bool, str, str)  # (success, message, orderid)
    bookingResult = pyqtSignal(bool, str, object)  # (success, message, info|None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.util: VenueUtil | None = None
        self.action = VenueAction.LOAD_VENUES
        self.venue_id: int = 0
        self.date_str: str = ""
        self._selections: list[tuple[int, int]] = []  # [(area_id, stock_id)]
        self._order_id: str = ""

    @property
    def session(self):
        return accounts.current.session_manager.get_session("venue")

    def _ensure_idle(self) -> bool:
        """线程空闲才允许启动新任务，避免 QThread 重入崩溃。"""
        return not self.isRunning()

    def load_venues(self):
        if not self._ensure_idle():
            return
        self.action = VenueAction.LOAD_VENUES
        self.start()

    def load_slots(self, venue_id: int, date_str: str):
        if not self._ensure_idle():
            return
        self.venue_id = venue_id
        self.date_str = date_str
        self.action = VenueAction.LOAD_SLOTS
        self.start()

    def do_book(self, venue_id: int, selections: list[tuple[int, int]]) -> bool:
        """预订一个或多个时段。selections: [(area_id, stock_id), ...]"""
        if not self._ensure_idle():
            return False
        self.venue_id = venue_id
        self._selections = selections
        self.action = VenueAction.BOOK
        self.start()
        return True

    def load_orders(self) -> bool:
        """加载全部订单。线程忙时返回 False。"""
        if not self._ensure_idle():
            return False
        self.action = VenueAction.LOAD_ORDERS
        self.start()
        return True

    def cancel_order(self, orderid: str):
        """取消订单。"""
        if not self._ensure_idle():
            return
        self._order_id = orderid
        self.action = VenueAction.CANCEL_ORDER
        self.start()

    def run(self):
        self.can_run = True
        acc = accounts.current
        if acc is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        def aborted() -> bool:
            """线程被请求中断（如账号切换）时提前退出。"""
            return self.isInterruptionRequested() or not self.can_run

        try:
            self.setIndeterminate.emit(True)

            if self.action != VenueAction.BOOK:
                # 查询类操作需要登录
                self.messageChanged.emit(self.tr("正在登录…"))
                self.session.ensure_login(
                    acc.username, acc.password,
                    account=acc,
                    mfa_provider=acc.session_manager.mfa_provider,
                )
                if aborted():
                    self.canceled.emit()
                    return

            if self.util is None:
                self.util = VenueUtil(self.session)

            if self.action == VenueAction.LOAD_VENUES:
                self.messageChanged.emit(self.tr("正在加载场馆…"))
                venues = self.util.get_venues()
                if aborted():
                    self.canceled.emit()
                    return
                self.venuesLoaded.emit(venues)

            elif self.action == VenueAction.LOAD_ORDERS:
                self.messageChanged.emit(self.tr("正在加载订单…"))
                orders = self.util.get_orders()
                if aborted():
                    self.canceled.emit()
                    return
                self.ordersLoaded.emit(orders)

            elif self.action == VenueAction.CANCEL_ORDER:
                self.messageChanged.emit(self.tr("正在取消订单…"))
                result = self.util.cancel_order(self._order_id)
                if aborted():
                    self.canceled.emit()
                    return
                code = str(result.get("result", ""))
                msg = str(result.get("message", ""))
                ok = code == "1"
                self.orderCanceled.emit(
                    ok, msg or (self.tr("取消成功") if ok else self.tr("取消失败")),
                    self._order_id)

            elif self.action == VenueAction.LOAD_SLOTS:
                self.messageChanged.emit(self.tr("正在加载时段…"))
                ok = self.util.get_available_slots(self.venue_id, self.date_str)
                locked = self.util.get_locked_slots(self.venue_id, self.date_str)
                if aborted():
                    self.canceled.emit()
                    return
                self.slotsLoaded.emit(ok, locked)

            elif self.action == VenueAction.BOOK:
                self.messageChanged.emit(self.tr("正在处理验证码…"))
                # 最多重试 3 次（验证码获取失败也算一次，继续重试）
                for attempt in range(3):
                    try:
                        # 取验证码（使用 session 的底层 HTTP 会话）
                        raw = self.session.backend.session
                        cid, bg, sl = fetch_captcha(raw)
                        move_x, conf = detect_gap(bg, sl)
                        track = gen_track(move_x)
                        yzm = build_yzm(track, cid)
                    except Exception:
                        _log.info("book: captcha fetch failed (attempt %d), retry",
                                  attempt + 1)
                        continue
                    if aborted():
                        self.canceled.emit()
                        return

                    self.messageChanged.emit(
                        self.tr("正在提交预订（第 {0} 次）…").format(attempt + 1))
                    result = self.util.book(
                        self.venue_id, self._selections, yzm)

                    code = result.get("result", "")
                    msg = result.get("message", "")
                    has_order = (isinstance(result.get("object"), dict)
                                 and result["object"].get("orderid"))

                    if code == "2" or has_order:
                        oid = result.get("object", {}).get("orderid", "")
                        price = result.get("object", {}).get("price", 0)
                        info = {"orderid": oid, "price": price}
                        self.bookingResult.emit(
                            True, self.tr("预订成功！订单号：{0}").format(oid), info)
                        self.hasFinished.emit()
                        return
                    elif "验证码" in msg or "captcha" in msg.lower():
                        continue  # 重试
                    else:
                        self.bookingResult.emit(
                            False, msg or self.tr("预订失败（{0}）").format(code), None)
                        self.hasFinished.emit()
                        return

                self.bookingResult.emit(False, self.tr("验证码识别失败，请重试"), None)

            self.hasFinished.emit()

        except VenueAPIError as e:
            # 如“未到可预订时间”等服务器提示页
            self.error.emit(self.tr("暂不可预订"), str(e))
            self.canceled.emit()
        except Exception as e:
            self.error.emit(self.tr("操作失败"), str(e))
            self.canceled.emit()
