"""体育场馆预约界面 - 仿照 LMSInterface 模式，两级页面。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QUrl
from PyQt5.QtGui import QColor, QDesktopServices
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QFrame, QHBoxLayout,
                             QSizePolicy, QHeaderView, QStackedWidget,
                             QTableWidgetItem, QCheckBox, QPushButton)
from qfluentwidgets import (ScrollArea, TitleLabel, StrongBodyLabel,
                            BodyLabel, CaptionLabel, FluentIcon, TableWidget,
                            FlowLayout, BreadcrumbBar, PrimaryPushButton,
                            TransparentToolButton, PushButton, Pivot,
                            InfoBar, InfoBarPosition, ComboBox,
                            CheckBox, MessageBox, MessageBoxBase, SubtitleLabel)

from .utils import StyleSheet, accounts, AccountDataManager, cfg
from .venues.venue import VenueInfo, AreaSlot, OrderInfo, VenueUtil
from .threads.VenueThread import VenueThread
from .threads.ProcessWidget import ProcessWidget
from .cards.venue_card import VenueCard, VenueSkeletonCard
from .sub_interfaces.lms.common import (
    PageStatus, create_retry_frame, apply_stretch_and_fixed_column_width)

_log = logging.getLogger("default")


# ============================= 起始页 =============================

class VenueStartPage(QFrame):
    """起始页：居中提示 + 查询按钮。"""

    queryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("venueStartPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.startFrame = QFrame(self)
        startLayout = QVBoxLayout(self.startFrame)

        self.startLabel = BodyLabel(
            self.tr("还没有场馆信息"), self.startFrame)
        self.startButton = PrimaryPushButton(
            self.tr("查询场馆"), self.startFrame)
        self.startButton.setFixedWidth(150)
        self.startButton.clicked.connect(self.queryRequested.emit)

        startLayout.addWidget(self.startLabel, alignment=Qt.AlignHCenter)
        startLayout.addWidget(self.startButton, alignment=Qt.AlignHCenter)

        layout.addStretch(1)
        layout.addWidget(self.startFrame,
                         alignment=Qt.AlignVCenter | Qt.AlignHCenter)
        layout.addStretch(1)

    def setInteractionEnabled(self, enabled: bool):
        self.startButton.setEnabled(enabled)


# ============================= 订单页 =============================

class OrderPage(QFrame):
    """我的订单：表格列出订单，可查看详情 / 取消 / 去支付。"""

    refreshRequested = pyqtSignal()
    retryRequested = pyqtSignal()
    orderClicked = pyqtSignal(object)     # OrderInfo
    cancelRequested = pyqtSignal(object)  # OrderInfo
    payRequested = pyqtSignal(object)     # OrderInfo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orderPage")
        self._orders: list[OrderInfo] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        # 顶部栏：提示 + 刷新
        topBar = QFrame(self)
        tb = QHBoxLayout(topBar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(12)
        self.refreshBtn = PushButton(FluentIcon.SYNC, self.tr("刷新"), topBar)
        self.refreshBtn.setFixedWidth(90)
        self.refreshBtn.clicked.connect(self.refreshRequested.emit)
        tb.addWidget(self.refreshBtn)
        self.hintLabel = CaptionLabel(self.tr(""), topBar)
        tb.addWidget(self.hintLabel)
        tb.addStretch(1)
        layout.addWidget(topBar)

        # 表格
        self.table = TableWidget(self)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # 加载失败重试（统一工厂）
        self.failFrame, self.retryBtn = create_retry_frame(self)
        layout.addWidget(self.failFrame)
        self.failFrame.setVisible(False)
        self.retryBtn.clicked.connect(self.retryRequested.emit)

    def setPageStatus(self, status: int):
        self.table.setVisible(status == PageStatus.NORMAL)
        self.failFrame.setVisible(status == PageStatus.ERROR)

    def setOrders(self, orders: list):
        """填充订单表格。"""
        self._orders = list(orders)
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        if not orders:
            self.table.setRowCount(1)
            self.table.setColumnCount(1)
            self.table.setItem(0, 0, QTableWidgetItem(self.tr("暂无订单")))
            self.hintLabel.setText(self.tr(""))
            return
        cols = [self.tr("状态"), self.tr("场馆"), self.tr("日期"),
                self.tr("金额"), self.tr("下单时间"), self.tr("操作")]
        self.table.setRowCount(len(orders))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        for r, o in enumerate(orders):
            first = o.details[0] if o.details else None
            self._setItem(r, 0, o.status_text,
                          color=self._status_color(o.status))
            self._setItem(r, 1, o.venue_name)
            self._setItem(r, 2, first.date if first else "")
            self._setItem(r, 3, f"¥{o.price:.2f}")
            self._setItem(r, 4, o.createdate)
            self._setActionCell(r, o)
        self.table.resizeColumnsToContents()
        # 操作列固定宽度，其余列拉伸（统一工具）
        self.table.setColumnWidth(5, 220)
        apply_stretch_and_fixed_column_width(self.table)
        self.hintLabel.setText(self.tr("共 {0} 单").format(len(orders)))

    def _setItem(self, row: int, col: int, text: str, color=None):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if color:
            item.setForeground(color)
        self.table.setItem(row, col, item)

    @staticmethod
    def _status_color(status: int):
        if status == 0:
            return QColor("#ed6a0c")   # 预订中
        if status == 1:
            return QColor("#2e7d32")   # 预订成功
        return QColor("#888888")        # 预订取消

    def _setActionCell(self, row: int, order: OrderInfo):
        """操作列：详情 + 去支付/取消/已取消。"""
        w = QWidget(self.table)
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(4)
        h.addStretch(1)
        # 详情（所有状态）
        btn = PushButton(self.tr("详情"), w)
        btn.setFixedSize(60, 26)
        btn.clicked.connect(
            lambda _, o=order: self.orderClicked.emit(o))
        h.addWidget(btn)
        if order.status == 0:
            btn = PushButton(self.tr("去支付"), w)
            btn.setFixedSize(72, 26)
            btn.clicked.connect(
                lambda _, o=order: self.payRequested.emit(o))
            h.addWidget(btn)
        if order.status == 0 or order.status == 1:
            btn = PushButton(self.tr("取消"), w)
            btn.setFixedSize(60, 26)
            btn.clicked.connect(
                lambda _, o=order: self.cancelRequested.emit(o))
            h.addWidget(btn)
        elif order.status == 2:
            lbl = CaptionLabel(self.tr("已取消"), w)
            lbl.setTextColor("#888888", "#999999")
            h.addWidget(lbl)
        h.addStretch(1)
        self.table.setCellWidget(row, 5, w)

    def clear(self):
        self._orders = []
        self.table.setRowCount(0)
        self.table.setColumnCount(0)


# ============================= 支付引导对话框 =============================

class PayDialog(MessageBoxBase):
    """支付引导：去登录（保持打开）/ 去支付（关闭并跳转）。"""

    def __init__(self, orderid: str, parent=None):
        super().__init__(parent=parent)
        self.orderid = str(orderid)

        self.titleLabel = SubtitleLabel(self.tr("去支付"), self)
        self.contentLabel = BodyLabel(
            self.tr("订单尚未支付，请先在浏览器中登录，再前往支付。\n\n"
                    "订单号：{0}").format(self.orderid), self)
        self.contentLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.contentLabel)

        # 去支付 = 主操作（Primary 蓝底），点击关闭并跳转
        self.yesButton.setText(self.tr("去支付"))
        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._onPay)
        # 去登录 = 普通按钮，点击保持对话框打开
        self.cancelButton.setText(self.tr("去登录"))
        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self._onLogin)
        # 关闭 = 普通按钮，直接关闭
        self.closeButton = PushButton(self.tr("关闭"), self.buttonGroup)
        self.closeButton.clicked.connect(self.reject)
        self.buttonLayout.addWidget(self.closeButton)

        self.widget.setMinimumWidth(420)

    def _onLogin(self):
        QDesktopServices.openUrl(QUrl(VenueUtil.LOGIN_URL))
        # 不关闭，用户登录后可继续点“去支付”

    def _onPay(self):
        QDesktopServices.openUrl(QUrl(VenueUtil.pay_url(self.orderid)))
        self.accept()


# ============================= 主界面 =============================

class VenueInterface(ScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._venues: list[VenueInfo] = []
        self._selected_id: int = 0
        self._selected_name: str = ""
        self._advancenum: int = 8  # 当前场馆单次最多可订数量
        self._venue_subpage: str = "list"  # 场馆页内部：list / slots
        self._title_hidden: bool = False  # 切到订单 Tab 后标题永久隐藏
        self._skeleton_cards: list[VenueSkeletonCard] = []
        self._venuePageCached = False
        self._enter_animations: list[QParallelAnimationGroup] = []
        self._last_slots_data: list[AreaSlot] = []
        self._slot_checkboxes: dict[tuple[int, int], CheckBox] = {}
        self._onlyNotice = None  # 当前显示的 InfoBar（通知去重）
        self._current_page = None  # 当前场馆页内部页面

        # ---- 根容器 ----
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        # ---- 标题 ----
        self.titleLabel = TitleLabel(self.tr("体育场馆"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.subtitleLabel = StrongBodyLabel(
            self.tr("查看场馆和可预订时段"), self.view)
        self.subtitleLabel.setContentsMargins(15, 5, 0, 0)
        self.subtitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.vBoxLayout.addWidget(self.subtitleLabel)
        self.titleSpacer = QWidget(self.view)
        self.titleSpacer.setFixedHeight(10)
        self.vBoxLayout.addWidget(self.titleSpacer)

        # ============ Tab 切换（体育场馆 / 我的订单）============
        self.pivotBar = QWidget(self.view)
        pivotLayout = QHBoxLayout(self.pivotBar)
        pivotLayout.setContentsMargins(10, 0, 0, 0)
        self.pivot = Pivot(self.pivotBar)
        self.pivot.addItem("venues", self.tr("体育场馆"),
                           onClick=lambda: self._onPivotChanged("venues"))
        self.pivot.addItem("orders", self.tr("我的订单"),
                           onClick=lambda: self._onPivotChanged("orders"))
        self.pivot.setCurrentItem("venues")
        pivotLayout.addWidget(self.pivot)
        pivotLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.pivotBar)

        # ============ 面包屑导航（两个 Tab 共享）============
        self.navFrame = QFrame(self.view)
        navLayout = QHBoxLayout(self.navFrame)
        navLayout.setContentsMargins(10, 0, 0, 0)
        navLayout.setSpacing(8)
        self.returnButton = TransparentToolButton(FluentIcon.RETURN, self.navFrame)
        self.returnButton.setToolTip(self.tr("返回"))
        self.returnButton.clicked.connect(self._onReturnButtonClicked)
        self.breadcrumbBar = BreadcrumbBar(self.navFrame)
        self.breadcrumbBar.setSpacing(20)
        self.breadcrumbBar.currentItemChanged.connect(self._onBreadcrumbChanged)
        navLayout.addWidget(self.returnButton, 0, Qt.AlignVCenter)
        navLayout.addWidget(self.breadcrumbBar, 1, Qt.AlignVCenter)
        self.vBoxLayout.addWidget(self.navFrame)

        # ============ Tab 内容（QStackedWidget）============
        self.stackHost = QStackedWidget(self.view)
        self.vBoxLayout.addWidget(self.stackHost, 1)

        # ============ 内容区（ProcessWidget + 所有页面）============
        self.contentFrame = QFrame(self.stackHost)
        self.stackHost.addWidget(self.contentFrame)
        self.contentLayout = QVBoxLayout(self.contentFrame)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.setSpacing(10)
        self.contentLayout.setAlignment(Qt.AlignTop)

        # 页面容器
        self.pageHost = QWidget(self.contentFrame)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.addWidget(self.pageHost)

        # ---- 页面：起始页 ----
        self.startPage = VenueStartPage(self.view)
        self.pageLayout.addWidget(self.startPage)
        self.startPage.queryRequested.connect(self._query)

        # ---- 页面：场馆列表 ----
        self.venuePage = QWidget(self.view)
        self.pageLayout.addWidget(self.venuePage)
        self.venuePage.setVisible(False)
        self.vpLayout = QVBoxLayout(self.venuePage)
        self.vpLayout.setContentsMargins(0, 0, 0, 0)
        self.vpLayout.setSpacing(10)
        self.vpLayout.setAlignment(Qt.AlignTop)

        self.venueSection = StrongBodyLabel(self.tr("场馆"), self.venuePage)
        self.vpLayout.addWidget(self.venueSection)

        self.venueHost = QWidget(self.venuePage)
        self.venueFlow = FlowLayout(self.venueHost, needAni=False)
        self.venueFlow.setContentsMargins(0, 0, 0, 0)
        self.venueFlow.setVerticalSpacing(12)
        self.venueFlow.setHorizontalSpacing(16)
        self.vpLayout.addWidget(self.venueHost)

        # 场馆页错误重试（统一工厂）
        self.venueFailFrame, self.venueRetryBtn = create_retry_frame(
            self.venuePage)
        self.vpLayout.addWidget(self.venueFailFrame)
        self.venueFailFrame.setVisible(False)
        self.venueRetryBtn.clicked.connect(self._query)

        self.contentLayout.addWidget(self.venuePage)

        # ---- 页面：时段表格 ----
        self.slotPage = QWidget(self.view)
        self.pageLayout.addWidget(self.slotPage)
        self.slotPage.setVisible(False)
        self.spLayout = QVBoxLayout(self.slotPage)
        self.spLayout.setContentsMargins(0, 0, 0, 0)
        self.spLayout.setSpacing(10)
        self.spLayout.setAlignment(Qt.AlignTop)

        # 日期
        dateBar = QFrame(self.slotPage)
        db = QHBoxLayout(dateBar)
        db.setContentsMargins(0, 0, 0, 0)
        db.setSpacing(12)
        db.addWidget(StrongBodyLabel(self.tr("日期："), dateBar))
        self.dateCombo = ComboBox(dateBar)
        self.dateCombo.setMinimumWidth(200)
        self.dateCombo.currentIndexChanged.connect(self._onDateChanged)
        db.addWidget(self.dateCombo)
        db.addStretch(1)
        self.spLayout.addWidget(dateBar)
        self._setupDates()

        # 场馆预订规则提示（提前天数 / 单次可订数量）
        self.venueRuleLabel = CaptionLabel(self.tr(""), self.slotPage)
        self.venueRuleLabel.setContentsMargins(0, 0, 0, 0)
        self.spLayout.addWidget(self.venueRuleLabel)

        # 表格（禁用选中，改用复选框）
        self.slotTable = TableWidget(self.slotPage)
        self.slotTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.slotTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        self.slotTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.slotTable.verticalHeader().setVisible(True)
        self.spLayout.addWidget(self.slotTable)

        # 预订按钮
        self.bookBtn = PrimaryPushButton(FluentIcon.SHOPPING_CART, self.tr("  预订"), self.slotPage)
        self.bookBtn.setFixedWidth(120)
        self.bookBtn.setVisible(False)
        self.bookBtn.clicked.connect(self._onBookClicked)
        self.spLayout.addWidget(self.bookBtn)

        # 时段页错误重试（统一工厂）
        self.slotFailFrame, self.slotRetryBtn = create_retry_frame(
            self.slotPage)
        self.spLayout.addWidget(self.slotFailFrame)
        self.slotFailFrame.setVisible(False)
        self.slotRetryBtn.clicked.connect(self._retryLoadSlots)

        # ---- 页面：我的订单 ----
        self.orderPage = OrderPage(self.stackHost)
        self.stackHost.addWidget(self.orderPage)
        self.orderPage.setVisible(False)
        self.orderPage.refreshRequested.connect(self.refreshOrders)
        self.orderPage.retryRequested.connect(self.refreshOrders)
        self.orderPage.orderClicked.connect(self._onOrderClicked)
        self.orderPage.cancelRequested.connect(self._onCancelOrder)
        self.orderPage.payRequested.connect(self._onPayOrder)

        # ---- 样式 ----
        StyleSheet.VENUE_INTERFACE.apply(self)
        self.setObjectName("VenueInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setMinimumWidth(500)

        # ---- 线程（和 LMS 一样单实例复用）----
        self.thread_ = VenueThread(self)
        self._connectThreadSignals()

        self.processWidget = ProcessWidget(
            self.thread_, self.view, stoppable=False, hide_on_end=True)
        self.processWidget.setVisible(False)
        # 放在 stackHost 外层，体育场馆 / 我的订单两个 Tab 都能显示进度条
        self.vBoxLayout.insertWidget(
            self.vBoxLayout.indexOf(self.stackHost), self.processWidget)

        accounts.currentAccountChanged.connect(self._onAccountChanged)

    def _setupDates(self, days: int = 7):
        """按可订天数生成日期栏（今天 ~ 今天+days-1）。"""
        days = max(1, min(int(days), 14))
        today = date.today()
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        self.dateCombo.blockSignals(True)
        self.dateCombo.clear()
        for i in range(days):
            d = today + timedelta(days=i)
            label = f"{d.isoformat()}（{'今天' if i == 0 else f'周{weekdays[d.weekday()]}'}）"
            self.dateCombo.addItem(label, userData=d.isoformat())
        self.dateCombo.setCurrentIndex(0)
        self.dateCombo.blockSignals(False)

    # ======================== 网络 ========================

    def _query(self):
        # 有缓存则先显示（类似 LMS 的 _showCachedCoursesIfAvailable）
        if self._isCacheEnabled():
            cached = self._readVenueCache()
            if cached:
                self._venuePageCached = True
                self._displayVenues(cached)
                self._setVenuePageStatus(PageStatus.NORMAL)
        self.processWidget.setVisible(True)
        self._lock()
        self.thread_.load_venues()

    def _loadSlots(self):
        if self._selected_id == 0:
            return
        dt = self.dateCombo.currentData() or date.today().isoformat()
        self.processWidget.setVisible(True)
        self._lock()
        self.thread_.load_slots(self._selected_id, dt)

    def _lock(self):
        self.returnButton.setEnabled(False)
        self.dateCombo.setEnabled(False)
        self.startPage.setInteractionEnabled(False)

    def _unlock(self):
        # 恢复后按面包屑根节点重新计算返回按钮状态
        self.dateCombo.setEnabled(True)
        self.startPage.setInteractionEnabled(True)
        self._updateReturnButtonState()

    # ======================== 回调 ========================

    @pyqtSlot(str, str)
    def _onThreadError(self, title, msg):
        _log.info("_onThreadError: %s %s", title, msg)
        self.error(title, msg)
        if self.stackHost.currentWidget() is self.orderPage:
            self.orderPage.setPageStatus(PageStatus.ERROR)
        elif self._current_page is self.slotPage:
            self._setSlotPageStatus(PageStatus.ERROR)
        elif self._venue_subpage == "list" and not self._venues:
            # 无缓存且加载失败，回到起始页让用户重试（标题可能已隐藏，重置）
            self._title_hidden = False
            self.switchPage(self.startPage)
            self.startPage.setInteractionEnabled(True)
        else:
            self._setVenuePageStatus(PageStatus.ERROR)

    @pyqtSlot()
    def _onThreadFinished(self):
        self._unlock()

    # ======================== Tab 切换 ========================

    def _onPivotChanged(self, key: str):
        """体育场馆 / 我的订单 Tab 切换。"""
        if key == "orders":
            self.stackHost.setCurrentWidget(self.orderPage)
            # 切到订单后标题永久隐藏（含切回场馆时）
            self._title_hidden = True
            self.titleLabel.setVisible(False)
            self.subtitleLabel.setVisible(False)
            self.titleSpacer.setVisible(False)
            # 订单页面包屑固定：仅“我的订单”，不可回退
            self.breadcrumbBar.blockSignals(True)
            self.breadcrumbBar.clear()
            self.breadcrumbBar.addItem(self.ROUTE_ORDERS, self.tr("我的订单"))
            self.breadcrumbBar.blockSignals(False)
            self._updateReturnButtonState()
            # 只在无数据时加载（切换 Tab 不重新加载）
            if not self.orderPage._orders:
                self.refreshOrders()
        else:
            self.stackHost.setCurrentWidget(self.contentFrame)
            # 标题已永久隐藏，不再恢复
            self.titleLabel.setVisible(False)
            self.subtitleLabel.setVisible(False)
            self.titleSpacer.setVisible(False)
            # 恢复场馆页内部面包屑
            self._syncVenueBreadcrumb()

    @staticmethod
    def _truncateBreadcrumbLabel(text: str, limit: int = 20) -> str:
        """截断过长的面包屑标题文本（对齐 LMS）。"""
        safe = str(text or "-")
        if len(safe) > limit:
            return f"{safe[:limit]}..."
        return safe

    def _syncVenueBreadcrumb(self):
        """按当前场馆页内部状态恢复面包屑（场馆列表 / 场馆列表 > 场馆名）。"""
        self.breadcrumbBar.blockSignals(True)
        self.breadcrumbBar.clear()
        self.breadcrumbBar.addItem(self.ROUTE_VENUES, self.tr("场馆列表"))
        if self._venue_subpage == "slots" and self._selected_name:
            self.breadcrumbBar.addItem(
                self.ROUTE_SLOTS,
                self._truncateBreadcrumbLabel(self._selected_name))
        self.breadcrumbBar.blockSignals(False)
        self._updateReturnButtonState()

    def refreshOrders(self):
        """触发订单加载（参考 LMS refreshCourses）。"""
        has_visible = bool(self.orderPage._orders)
        self.orderPage.setPageStatus(
            PageStatus.NORMAL if has_visible else PageStatus.LOADING)
        self.processWidget.setVisible(True)
        self._lock()
        if not self.thread_.load_orders():
            # 线程忙（如场馆加载中），恢复 UI 状态避免卡住
            self.processWidget.setVisible(False)
            self._unlock()

    @pyqtSlot(list)
    def _onOrdersLoaded(self, orders):
        self.orderPage.setOrders(orders)
        self.orderPage.setPageStatus(PageStatus.NORMAL)
        self.success(self.tr("已更新"), self.tr("共 {0} 个订单").format(len(orders)))

    @pyqtSlot(bool, str, str)
    def _onOrderCanceled(self, ok: bool, msg: str, orderid: str):
        self._unlock()
        self.processWidget.setVisible(False)
        if ok:
            self.success(self.tr("取消成功"), msg)
            # 仅订单页可见时刷新，避免干扰场馆页操作
            if self.stackHost.currentWidget() is self.orderPage:
                self.refreshOrders()
        else:
            self.error(self.tr("取消失败"), msg)

    @pyqtSlot(object)
    def _onOrderClicked(self, order):
        """点击订单行 → 详情弹窗。"""
        lines = [self.tr("订单号：{0}").format(order.orderid),
                 self.tr("下单时间：{0}").format(order.createdate),
                 self.tr("场馆：{0}").format(order.venue_name),
                 ""]
        for d in order.details:
            lines.append(self.tr("  {0}  {1}  {2}").format(
                d.date, d.time_slot, d.area_name))
        lines.append("")
        lines.append(self.tr("合计：¥{0:.2f}").format(order.price))
        box = MessageBox(self.tr("订单详情"), "\n".join(lines),
                         self.window())
        box.yesButton.setText(self.tr("关闭"))
        box.cancelButton.setVisible(False)
        box.exec_()

    @pyqtSlot(object)
    def _onCancelOrder(self, order):
        """取消订单：确认后提交。"""
        box = MessageBox(
            self.tr("取消订单"),
            self.tr("确定要取消订单 {0} 吗？\n\n支付金额将于 3 个工作日内"
                    "原路退还至一卡通账户").format(order.orderid),
            self.window())
        box.yesButton.setText(self.tr("确认"))
        box.cancelButton.setText(self.tr("取消"))
        if not box.exec_():
            return
        self.processWidget.setVisible(True)
        self._lock()
        self.thread_.cancel_order(order.orderid)

    @pyqtSlot(object)
    def _onPayOrder(self, order):
        """去支付：弹双按钮（去登录 / 去支付）后拉起系统浏览器。"""
        self._openPayDialog(order.orderid)

    def _openPayDialog(self, orderid: str):
        """支付引导对话框：去登录（保持打开） / 去支付（关闭并跳转）。"""
        dlg = PayDialog(orderid, self.window())
        dlg.exec_()

    # ======================== 页面状态 ========================

    def _setVenuePageStatus(self, status: int):
        ok = status == PageStatus.NORMAL
        loading = status == PageStatus.LOADING
        self.venueHost.setVisible(ok)
        self.venueSection.setVisible(ok or loading)
        self.venueFailFrame.setVisible(status == PageStatus.ERROR)
        if loading:
            self._showSkeletons()
        else:
            self._clearSkeletons()

    def _showSkeletons(self):
        self._clearSkeletons()
        for _ in range(6):
            sk = VenueSkeletonCard(self.venueHost)
            self.venueFlow.addWidget(sk)
            self._skeleton_cards.append(sk)

    def _clearSkeletons(self):
        for sk in self._skeleton_cards:
            try:
                self.venueFlow.removeWidget(sk)
                sk.deleteLater()
            except RuntimeError:
                pass  # 已被 _clearContainer 删除
        self._skeleton_cards.clear()

    def _setSlotPageStatus(self, status: int):
        self.slotTable.setVisible(status == PageStatus.NORMAL)
        self.slotFailFrame.setVisible(status == PageStatus.ERROR)

    def _retryLoadSlots(self):
        self._setSlotPageStatus(PageStatus.NORMAL)
        self._loadSlots()

    # ======================== 预订 ========================

    def _onCheckChanged(self, row: int, col: int, state: int, cb=None):
        """复选框状态变化：允许多选，但不超过 advancenum；
        有勾选则显示预订按钮。"""
        if state == 2 and cb is not None and self._advancenum > 0:
            total = sum(1 for c in self._slot_checkboxes.values()
                        if c.isChecked())
            if total > self._advancenum:
                # 用 setCheckState 而非 setChecked：setChecked 会让 Qt 内部
                # checked 标志脱节，导致下一次点击信号丢失、误选中
                cb.blockSignals(True)
                cb.setCheckState(Qt.Unchecked)
                cb.blockSignals(False)
                self.warning(
                    self.tr("超出数量限制"),
                    self.tr("单次最多可预订 {0} 个时段").format(
                        self._advancenum))
                return
        checked = any(cb_.isChecked()
                      for cb_ in self._slot_checkboxes.values())
        self.bookBtn.setVisible(checked)

    @staticmethod
    def _sortAreas(areas) -> list:
        """场地名自然排序（场地1 < 场地2 < ... < 场地10）。"""
        def key(x):
            m = re.search(r'\d+', x)
            return (int(m.group()), x) if m else (float('inf'), x)
        return sorted(set(areas), key=key)

    def _selected_slots(self) -> list[AreaSlot]:
        """收集所有勾选的时段，返回 AreaSlot 列表。"""
        all_slots = getattr(self, '_last_slots_data', [])
        if not all_slots:
            return []
        times = sorted(set(s.time_slot for s in all_slots))
        areas = self._sortAreas(s.area_name for s in all_slots)
        lookup = {(s.area_name, s.time_slot): s for s in all_slots}
        selected: list[AreaSlot] = []
        for (r, c), cb in self._slot_checkboxes.items():
            if not cb.isChecked():
                continue
            if r >= len(times) or c >= len(areas):
                continue
            s = lookup.get((areas[c], times[r]))
            if s is not None and s.is_available:
                selected.append(s)
        return selected

    def _onBookClicked(self):
        """收集勾选时段，弹确认框后提交。"""
        selected = self._selected_slots()
        if not selected:
            self.error(self.tr("请先选择"), self.tr("请勾选至少一个可预订的时段"))
            return

        total = sum(s.price for s in selected)
        lines = [self.tr("场馆：{0}").format(self._selected_name),
                 self.tr("日期：{0}").format(
                     self.dateCombo.currentText().split("（")[0])]
        for s in selected:
            lines.append(self.tr("  {0}  {1}  ¥{2:.0f}").format(
                s.time_slot, s.area_name, s.price))
        lines.append(self.tr("共 {0} 个时段，合计 ¥{1:.0f}").format(
            len(selected), total))

        box = MessageBox(self.tr("确认预订"), "\n".join(lines), self.window())
        if not box.exec_():
            return

        self.bookBtn.setVisible(False)
        self.processWidget.setVisible(True)
        self._lock()
        selections = [(s.area_id, s.stock_id) for s in selected]
        if not self.thread_.do_book(self._selected_id, selections):
            # 线程忙（理论上 _lock 已防，兜底提示）
            self._unlock()
            self.processWidget.setVisible(False)
            self.error(self.tr("操作进行中"), self.tr("请等待当前操作完成"))

    def _onBookingResult(self, success: bool, msg: str, info=None):
        self._unlock()
        self.processWidget.setVisible(False)
        if success:
            self.success(self.tr("预订成功"), msg)
            # 有价格订单 → 弹支付引导
            if isinstance(info, dict):
                oid = info.get("orderid", "")
                price = float(info.get("price") or 0)
                if oid and price > 0:
                    self._promptPay(oid)
            # 刷新时段
            self._loadSlots()
        else:
            self.error(self.tr("预订失败"), msg)

    def _promptPay(self, orderid: str):
        """提交成功且需支付时，弹支付引导（去登录 / 去支付）。"""
        self._openPayDialog(orderid)

    def _onVenuesLoaded(self, venues):
        was_cached = self._venuePageCached
        self._venuePageCached = False
        if self._isCacheEnabled():
            self._writeVenueCache(venues)
        self._displayVenues(venues)
        self._setVenuePageStatus(PageStatus.NORMAL)
        if venues:
            if was_cached:
                self.success(self.tr("场馆已是最新"), self.tr("缓存与网络数据一致"))
            else:
                self.success(self.tr("加载完成"), self.tr("已获取 {0} 个场馆").format(len(venues)))
        else:
            self.success(self.tr("暂无场馆"), self.tr("当前账号未获取到场馆"))

    def _displayVenues(self, venue_data):
        """显示场馆列表（从缓存或网络数据）。"""
        if self.startPage.isVisible():
            self.switchPage(self.venuePage)
        self._clearContainer()
        # 转成 VenueInfo 对象（缓存数据可能是 dict）
        self._venues = [VenueInfo(v["id"], v["name"], v.get("address", ""),
                                  v.get("icon", ""), v.get("category", ""),
                                  advanceday=v.get("advanceday", 7),
                                  advancenum=v.get("advancenum", 8))
                        if isinstance(v, dict)
                        else v for v in venue_data]
        if not self._venues:
            self.venueFlow.addWidget(
                BodyLabel(self.tr("暂无场馆"), self.venueHost))
            return
        for v in self._venues:
            card = VenueCard(v.id, v.name, v.address, self.venueHost)
            card.venueClicked.connect(self._onVenueClicked)
            self.venueFlow.addWidget(card)
        self._animateCardsIn()

    def _animateCardsIn(self):
        """播放场馆卡片出现的动画（仿照 LMS 的 _animateCourseCardsIn）。"""
        for ani in self._enter_animations:
            ani.stop()
        self._enter_animations.clear()

        cards = self.venueFlow.findChildren(VenueCard)
        if not cards:
            return

        self.venueFlow.activate()
        ordered = sorted(cards, key=lambda c: (c.y(), c.x()))
        row_tolerance = 12
        rows: list[list] = []
        for card in ordered:
            if not rows or abs(card.y() - rows[-1][0].y()) > row_tolerance:
                rows.append([card])
            else:
                rows[-1].append(card)
        for row in rows:
            row.sort(key=lambda c: c.x())

        duration = 360
        within_row_step = 70
        between_row_gap = 30
        row_start_delay = 0

        for row in rows:
            for col_idx, card in enumerate(row):
                delay = row_start_delay + col_idx * within_row_step
                card.setMinimumHeight(0)
                card.setMaximumHeight(0)
                card.updateGeometry()

                min_h = QPropertyAnimation(card, b"minimumHeight", card)
                min_h.setDuration(duration)
                min_h.setStartValue(0)
                min_h.setEndValue(160)
                min_h.setEasingCurve(QEasingCurve.OutBack)

                max_h = QPropertyAnimation(card, b"maximumHeight", card)
                max_h.setDuration(duration)
                max_h.setStartValue(0)
                max_h.setEndValue(160)
                max_h.setEasingCurve(QEasingCurve.OutBack)

                group = QParallelAnimationGroup(self)
                group.addAnimation(min_h)
                group.addAnimation(max_h)

                def finalize(target=card):
                    try:
                        target.setMinimumHeight(160)
                        target.setMaximumHeight(160)
                        target.updateGeometry()
                    except RuntimeError:
                        return
                group.finished.connect(finalize)
                self._enter_animations.append(group)

                QTimer.singleShot(delay, group.start)

            row_anim_span = (len(row) - 1) * within_row_step + duration
            row_start_delay += row_anim_span + between_row_gap

    def _onSlotsLoaded(self, ok_slots, locked_slots):
        self._setSlotPageStatus(PageStatus.NORMAL)
        self._last_slots_data = list(ok_slots) + list(locked_slots)
        all_slots = self._last_slots_data
        if not all_slots:
            self.slotTable.setRowCount(0)
            self.slotTable.setColumnCount(0)
            self.success(self.tr("无时段"), self.tr("该场馆当天暂无可用时段"))
            return

        self.slotTable.setRowCount(0)
        self.slotTable.setColumnCount(0)
        self._slot_checkboxes.clear()
        areas = self._sortAreas(s.area_name for s in all_slots)
        times = sorted(set(s.time_slot for s in all_slots))
        lookup = {(s.area_name, s.time_slot): s for s in all_slots}

        self.slotTable.setRowCount(len(times))
        self.slotTable.setColumnCount(len(areas))
        self.slotTable.setHorizontalHeaderLabels(areas)
        self.slotTable.setVerticalHeaderLabels(times)

        for r, ts in enumerate(times):
            for c, an in enumerate(areas):
                s = lookup.get((an, ts))
                cb = CheckBox()
                cb.setFixedSize(90, 26)
                if s is not None and s.is_available:
                    cb.setText(self.tr("可订"))
                    cb.setTextColor("#2e7d32", "#81c784")
                    cb.stateChanged.connect(
                        lambda state, rr=r, cc=c, cbc=cb:
                        self._onCheckChanged(rr, cc, state, cbc))
                    self._slot_checkboxes[(r, c)] = cb
                else:
                    cb.setText(self.tr("占用") if s else self.tr("不可用"))
                    cb.setEnabled(False)
                self.slotTable.setCellWidget(r, c, cb)

        self.slotTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.Fixed)
        self.slotTable.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        # 设最小列宽
        for c in range(len(areas)):
            self.slotTable.setColumnWidth(c, 100)
        self.success(self.tr("已更新"),
                      self.tr("可用 {0} / 已占用 {1}").format(
                          len(ok_slots), len(locked_slots)))

    # ======================== 页面切换 ========================

    def switchPage(self, page):
        """切换页面并更新标题/导航可见性（对齐 LMS：维护当前页 + 滚动回顶）。"""
        self._current_page = page
        pages = (self.startPage, self.venuePage, self.slotPage)
        for p in pages:
            p.setVisible(p is page)
        if page is self.slotPage:
            self._venue_subpage = "slots"
        elif page is self.venuePage or page is self.startPage:
            self._venue_subpage = "list"
        self._updatePageHeader(page)
        self.pageHost.adjustSize()
        self.view.adjustSize()
        self.verticalScrollBar().setValue(0)

    def _updatePageHeader(self, page):
        """标题仅起始页显示且未切过订单 Tab；面包屑常驻更新。"""
        on_start_page = (page is self.startPage and not self._title_hidden)
        self.titleLabel.setVisible(on_start_page)
        self.subtitleLabel.setVisible(on_start_page)
        self.titleSpacer.setVisible(on_start_page)
        if self.stackHost.currentWidget() is not self.orderPage:
            self._syncVenueBreadcrumb()

    def _updateReturnButtonState(self):
        self.returnButton.setEnabled(len(self.breadcrumbBar.items) > 1)

    def _onVenueClicked(self, vid):
        _log.info("_onVenueClicked: vid=%s type=%s", vid, type(vid).__name__)
        for v in self._venues:
            if str(v.id) == str(vid):
                self._selected_id = v.id
                self._selected_name = v.name
                self._advancenum = v.advancenum
                # 按场馆 advanceday 动态生成日期栏
                self._setupDates(v.advanceday)
                # 显示预订规则提示
                self.venueRuleLabel.setText(self.tr(
                    "本场馆提前 {0} 天开放预订，单次最多可订 {1} 个时段"
                ).format(v.advanceday, v.advancenum))
                break
        self.switchPage(self.slotPage)
        self._setSlotPageStatus(PageStatus.LOADING)
        self._loadSlots()

    def _goBack(self):
        self.switchPage(self.venuePage)
        self.slotTable.setRowCount(0)
        self.slotTable.setColumnCount(0)
        self.venueRuleLabel.setText("")
        self.verticalScrollBar().setValue(0)

    def _onDateChanged(self):
        if self.slotPage.isVisible():
            self._loadSlots()

    VENUE_CACHE = "venue_venues_cache.json"
    ROUTE_VENUES = "venues"
    ROUTE_SLOTS = "slots"
    ROUTE_ORDERS = "orders"

    def _cachePath(self) -> str | None:
        cur = accounts.current
        if cur is None:
            return None
        return AccountDataManager(cur).path(self.VENUE_CACHE)

    def _isCacheEnabled(self) -> bool:
        return bool(cfg.venueCacheEnable.value)

    def _readVenueCache(self) -> list[dict]:
        if not self._isCacheEnabled():
            return []
        path = self._cachePath()
        if not path:
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return []

    def _writeVenueCache(self, venues: list):
        path = self._cachePath()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([{"id": v.id, "name": v.name,
                            "address": v.address, "icon": v.icon,
                            "category": getattr(v, "category", ""),
                            "advanceday": getattr(v, "advanceday", 7),
                            "advancenum": getattr(v, "advancenum", 8)}
                           for v in venues], f, ensure_ascii=False)
        except (OSError, TypeError, ValueError):
            pass

    def _onReturnButtonClicked(self):
        if len(self.breadcrumbBar.items) <= 1:
            self._updateReturnButtonState()
            return
        self.breadcrumbBar.setCurrentIndex(len(self.breadcrumbBar.items) - 2)

    def _onBreadcrumbChanged(self, route_key: str):
        if route_key == self.ROUTE_VENUES:
            self._goBack()
    def _connectThreadSignals(self):
        self.thread_.venuesLoaded.connect(self._onVenuesLoaded)
        self.thread_.slotsLoaded.connect(self._onSlotsLoaded)
        self.thread_.ordersLoaded.connect(self._onOrdersLoaded)
        self.thread_.orderCanceled.connect(self._onOrderCanceled)
        self.thread_.bookingResult.connect(self._onBookingResult)
        self.thread_.error.connect(self._onThreadError)
        self.thread_.finished.connect(self._onThreadFinished)

    def _cleanupThread(self):
        """账号切换时安全停止后台线程，并重连信号避免旧信号干扰新账号。"""
        for sig in (self.thread_.venuesLoaded, self.thread_.slotsLoaded,
                    self.thread_.ordersLoaded, self.thread_.orderCanceled,
                    self.thread_.bookingResult, self.thread_.error,
                    self.thread_.finished):
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass
        if self.thread_.isRunning():
            self.thread_.requestInterruption()
            self.thread_.wait(3000)
        self._connectThreadSignals()

    def _onAccountChanged(self):
        self._venues = []
        self._selected_id = 0
        self._selected_name = ""
        self._advancenum = 8
        self._venue_subpage = "list"
        self._title_hidden = False  # 换账号重置标题显示
        self.venueRuleLabel.setText("")
        self.orderPage.clear()
        self._onPivotChanged("venues")
        self._venuePageCached = False
        self._clearContainer()
        self._cleanupThread()
        self.slotTable.setRowCount(0)
        self.slotTable.setColumnCount(0)
        self.switchPage(self.startPage)

    def success(self, title, msg, duration=2000,
                position=InfoBarPosition.TOP_RIGHT, parent=None):
        """显示成功通知（关闭上一条，后台时驻留可关闭）。"""
        self._show_notice("success", title, msg, duration, position, parent)

    def warning(self, title, msg, duration=2500,
                position=InfoBarPosition.TOP_RIGHT, parent=None):
        """显示警告通知。"""
        self._show_notice("warning", title, msg, duration, position, parent)

    def error(self, title, msg, duration=3000,
              position=InfoBarPosition.TOP_RIGHT, parent=None):
        """显示错误通知。"""
        self._show_notice("error", title, msg, duration, position, parent)

    def _show_notice(self, kind, title, msg, duration, position, parent):
        """统一通知实现（与 LMS/EmptyRoom 一致）。"""
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                pass
            self._onlyNotice = None
        target = parent or self.window()
        factory = getattr(InfoBar, kind)
        if self.window().isActiveWindow():
            self._onlyNotice = factory(
                title, msg, duration=duration, position=position, parent=target)
        else:
            self._onlyNotice = factory(
                title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT,
                parent=target, isClosable=True)

    # ======================== 工具 ========================

    def _clearContainer(self):
        while self.venueFlow.count():
            w = self.venueFlow.takeAt(0)  # FlowLayout 直接返回 widget
            if w:
                w.deleteLater()
