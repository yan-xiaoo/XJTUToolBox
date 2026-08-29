"""图书馆座位界面 - 三层可视化选座。

层级：校区/楼层（场馆式卡片）→ 楼层地图（选区域）→ 座位地图（选座/预约）。
楼层列表写死自服务端 floor-selector 真实命名（CAMPUS_FLOORS），区域数异步探测；
进入卡片页后标题简介进入精简模式（紧凑小字 + 面包屑）。
"""

from __future__ import annotations

import logging
import re

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QFrame, QHBoxLayout,
                             QSizePolicy, QStackedWidget)
from qfluentwidgets import (ScrollArea, TitleLabel, StrongBodyLabel,
                            CaptionLabel, FluentIcon, BreadcrumbBar,
                            PrimaryPushButton, PushButton, TransparentToolButton,
                            Pivot, FlowLayout, InfoBar, InfoBarPosition,
                            BodyLabel, ElevatedCardWidget, SubtitleLabel,
                            IconWidget, MessageBox)

from library import CAMPUSES, CAMPUS_FLOORS, FLOOR_PREFIX_CAMPUS, Library
from library.seats import PREFIX_CAMPUS_ID
from .utils import StyleSheet, accounts
from .threads.CampusFeatureThread import CampusFeatureThread
from .threads.ProcessWidget import ProcessWidget
from .components.VisualSeatView import VisualSeatView
from .sub_interfaces.lms.common import PageStatus, create_retry_frame

_log = logging.getLogger("default")


def floor_label(code: str) -> str:
    """楼层码 -> 展示名（inno1floor -> 创新港 1 楼；yanta4floor -> 雁塔 4 楼）。"""
    m = re.match(r"([a-z]+)(\d+)floor", code)
    if not m:
        return code
    campus = FLOOR_PREFIX_CAMPUS.get(m.group(1), m.group(1))
    return f"{campus} {m.group(2)} 楼"


class FloorCard(ElevatedCardWidget):
    """校区楼层卡片（对齐体育场馆卡片样式）。"""

    picked = pyqtSignal(str)  # floor_code

    def __init__(self, floor_code: str, campus_name: str, parent=None):
        super().__init__(parent)
        self._floor_code = floor_code
        self.setFixedSize(200, 120)
        self.setBorderRadius(12)

        self.titleLabel = SubtitleLabel(floor_label(floor_code), self)

        bottom = QHBoxLayout()
        icon = IconWidget(FluentIcon.BOOK_SHELF, self)
        icon.setFixedSize(14, 14)
        campusLabel = CaptionLabel(campus_name, self)
        bottom.addWidget(icon)
        bottom.addWidget(campusLabel)
        bottom.addStretch(1)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.addWidget(self.titleLabel)
        v.addStretch(1)
        v.addLayout(bottom)

        for w in (self.titleLabel, icon, campusLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        self.picked.emit(self._floor_code)
        super().mouseReleaseEvent(event)


class LibraryInterface(ScrollArea):
    """图书馆座位主界面：三层可视化选座。"""

    ROUTE_SEATS = "seats"
    ROUTE_BOOKING = "booking"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._area_names: dict[str, str] = {}
        self._title_hidden = False
        self._last_shown_tab = self.ROUTE_SEATS
        self._floor_code = ""
        self._area_code = ""
        self._floors_built = False
        self._campus_switched = False
        self._prev_campus = ""

        # ---- 根容器 ----
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        # ---- 标题（完整模式）----
        self.titleLabel = TitleLabel(self.tr("图书馆"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        self.subtitleLabel = StrongBodyLabel(
            self.tr("可视化选座：换座、签到与预约"), self.view)
        self.subtitleLabel.setContentsMargins(15, 5, 0, 0)
        self.subtitleLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.vBoxLayout.addWidget(self.subtitleLabel)
        self.titleSpacer = QWidget(self.view)
        self.titleSpacer.setFixedHeight(10)
        self.vBoxLayout.addWidget(self.titleSpacer)

        # ============ Tab 切换 ============
        self.pivotBar = QWidget(self.view)
        pivotLayout = QHBoxLayout(self.pivotBar)
        pivotLayout.setContentsMargins(10, 0, 0, 0)
        self.pivot = Pivot(self.pivotBar)
        self.pivot.addItem(self.ROUTE_SEATS, self.tr("可预约座位"),
                           onClick=lambda: self._onPivotChanged(self.ROUTE_SEATS))
        self.pivot.addItem(self.ROUTE_BOOKING, self.tr("我的预约"),
                           onClick=lambda: self._onPivotChanged(self.ROUTE_BOOKING))
        self.pivot.setCurrentItem(self.ROUTE_SEATS)
        pivotLayout.addWidget(self.pivot)
        pivotLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.pivotBar)

        # ============ 面包屑导航 ============
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

        # ============ Tab 内容 ============
        self.stackHost = QStackedWidget(self.view)
        self.vBoxLayout.addWidget(self.stackHost, 1)

        self.contentFrame = QFrame(self.stackHost)
        self.stackHost.addWidget(self.contentFrame)
        self.contentLayout = QVBoxLayout(self.contentFrame)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.setSpacing(10)
        self.contentLayout.setAlignment(Qt.AlignTop)

        self.pageHost = QWidget(self.contentFrame)
        self.pageLayout = QVBoxLayout(self.pageHost)
        self.pageLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.addWidget(self.pageHost)

        # ---- L1：校区 / 楼层（小标题 + 卡片流）----
        self.floorsPage = QWidget(self.view)
        self.floorsPage.setVisible(False)
        self.fpLayout = QVBoxLayout(self.floorsPage)
        self.fpLayout.setContentsMargins(0, 0, 0, 0)
        self.fpLayout.setSpacing(14)
        self.fpLayout.setAlignment(Qt.AlignTop)
        self.pageLayout.addWidget(self.floorsPage)

        # ---- L2：楼层地图 ----
        self.floorMapPage = QWidget(self.view)
        self.floorMapPage.setVisible(False)
        self.fmLayout = QVBoxLayout(self.floorMapPage)
        self.fmLayout.setContentsMargins(0, 0, 0, 0)
        self.fmLayout.addWidget(CaptionLabel(
            self.tr("楼层平面图：点击区域进入座位地图。滚轮缩放、拖拽平移、双击还原。"),
            self.floorMapPage))
        self.floorMapView = VisualSeatView(self.floorMapPage)
        self.fmLayout.addWidget(self.floorMapView, 1)
        self.pageLayout.addWidget(self.floorMapPage)

        # ---- L3：区域座位地图 ----
        self.areaMapPage = QWidget(self.view)
        self.areaMapPage.setVisible(False)
        self.amLayout = QVBoxLayout(self.areaMapPage)
        self.amLayout.setContentsMargins(0, 0, 0, 0)
        self.amLabel = CaptionLabel(
            self.tr("绿色为可选座位，灰色为已占用；悬停高亮，点击可选座位预约。"),
            self.areaMapPage)
        self.amLayout.addWidget(self.amLabel)
        self.areaMapView = VisualSeatView(self.areaMapPage)
        self.amLayout.addWidget(self.areaMapView, 1)
        self.pageLayout.addWidget(self.areaMapPage)

        # ---- 我的预约（居中大字 + 按状态操作）----
        self.bookingPage = QWidget(self.stackHost)
        self.stackHost.addWidget(self.bookingPage)
        self.bookingPage.setVisible(False)
        bpLayout = QVBoxLayout(self.bookingPage)
        bpLayout.setContentsMargins(0, 0, 0, 0)
        bpLayout.setSpacing(16)
        bpLayout.setAlignment(Qt.AlignCenter)

        # 刷新按钮（顶部）
        bar = QFrame(self.bookingPage)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        self.bookingRefresh = PrimaryPushButton(self.tr("刷新预约"), bar)
        self.bookingRefresh.setFixedWidth(120)
        self.bookingRefresh.clicked.connect(self._refreshBooking)
        bl.addWidget(self.bookingRefresh)
        bl.setAlignment(Qt.AlignCenter)
        bpLayout.addWidget(bar)

        # 座位大字（跟随主题色，暗色模式自动适配）
        self.bookingSeat = SubtitleLabel(self.bookingPage)
        self.bookingSeat.setAlignment(Qt.AlignHCenter)
        booking_font = self.bookingSeat.font()
        booking_font.setPointSize(28)
        booking_font.setBold(True)
        self.bookingSeat.setFont(booking_font)
        self.bookingSeat.hide()
        bpLayout.addWidget(self.bookingSeat)

        self.bookingDetail = BodyLabel(self.bookingPage)
        self.bookingDetail.setAlignment(Qt.AlignHCenter)
        self.bookingDetail.setWordWrap(True)
        bpLayout.addWidget(self.bookingDetail)

        # 操作按钮行（按预约状态动态生成）
        self.bookingActions = QHBoxLayout()
        self.bookingActions.setSpacing(12)
        self.bookingActions.addStretch(1)
        bpLayout.addLayout(self.bookingActions)
        self.bookingActions.addStretch(1)
        self._booking_action_urls: dict[str, str] = {}

        self.bookingFail, self.bookingRetry = create_retry_frame(self.bookingPage)
        bpLayout.addWidget(self.bookingFail)
        self.bookingFail.setVisible(False)
        self.bookingRetry.clicked.connect(self._refreshBooking)
        bpLayout.addStretch(1)

        # ---- 样式 ----
        StyleSheet.LIBRARY_INTERFACE.apply(self)
        self.setObjectName("LibraryInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setMinimumWidth(500)

        # ---- 线程与加载条 ----
        self.thread_ = None
        self.processWidget = None
        self.jobSlot = QWidget(self.view)
        self.jobLayout = QVBoxLayout(self.jobSlot)
        self.jobLayout.setContentsMargins(0, 0, 0, 0)
        self.jobLayout.setSpacing(0)
        self.vBoxLayout.insertWidget(self.vBoxLayout.indexOf(self.stackHost), self.jobSlot)

        accounts.currentAccountChanged.connect(self._onAccountChanged)

        self.floorMapView.seatClicked.connect(self._openAreaMap)
        self.areaMapView.seatClicked.connect(self._onSeatBookRequested)
        self.floorMapView.backRequested.connect(self._backToFloors)
        self.areaMapView.backRequested.connect(self._backToFloor)

        self._build_floor_cards()
        self.switchPage(self.floorsPage)
        self._syncBreadcrumb()
        self._apply_booking_colors()

    # ======================== 楼层卡片（静态构建 + 异步区域数）====================

    def _build_floor_cards(self):
        """楼层写死（CAMPUS_FLOORS），进入即可见全部卡片；区域数异步探测后更新。"""
        if self._floors_built:
            return
        self._floors_built = True
        for campus, campus_name in CAMPUSES.items():
            codes = CAMPUS_FLOORS.get(campus, [])
            if not codes:
                continue
            section = QWidget(self.floorsPage)
            sl = QVBoxLayout(section)
            sl.setContentsMargins(0, 0, 0, 0)
            sl.setSpacing(8)
            sl.addWidget(StrongBodyLabel(campus_name, section))
            flowHost = QWidget(section)
            flow = FlowLayout(flowHost, needAni=False)
            flow.setContentsMargins(0, 0, 0, 0)
            flow.setVerticalSpacing(12)
            flow.setHorizontalSpacing(16)
            for code in codes:
                card = FloorCard(code, campus_name, flowHost)
                card.picked.connect(self._openFloorMap)
                flow.addWidget(card)
            sl.addWidget(flowHost)
            self.fpLayout.addWidget(section)

    # ======================== 页面切换与头部 ========================

    def switchPage(self, page):
        for p in (self.floorsPage, self.floorMapPage, self.areaMapPage):
            p.setVisible(p is page)
        self._updatePageHeader(page)
        self.pageHost.adjustSize()
        self.view.adjustSize()
        self.verticalScrollBar().setValue(0)

    def _updatePageHeader(self, page):
        """L1 显示大标题+简介；进入卡片页后精简模式（紧凑小字）。"""
        on_start = (page is self.floorsPage and not self._title_hidden)
        self.titleLabel.setVisible(on_start)
        self.subtitleLabel.setVisible(on_start)
        self.titleSpacer.setVisible(on_start)

    def _onPivotChanged(self, key: str):
        self._last_shown_tab = key
        self._title_hidden = True
        self.titleLabel.setVisible(False)
        self.subtitleLabel.setVisible(False)
        self.titleSpacer.setVisible(False)
        self._apply_booking_colors()
        if key == self.ROUTE_BOOKING:
            self.stackHost.setCurrentWidget(self.bookingPage)
        else:
            self.stackHost.setCurrentWidget(self.contentFrame)
            self.switchPage(self.floorsPage)
        self._syncBreadcrumb()

    # ======================== 面包屑 / 返回 ========================

    def _syncBreadcrumb(self):
        self.breadcrumbBar.blockSignals(True)
        self.breadcrumbBar.clear()
        if self._last_shown_tab == self.ROUTE_BOOKING:
            # 我的预约：固定单级，不显示座位层级
            self.breadcrumbBar.addItem("booking", self.tr("我的预约"))
        else:
            self.breadcrumbBar.addItem(self.ROUTE_SEATS, self.tr("可预约座位"))
            if self._floor_code:
                self.breadcrumbBar.addItem("floor", floor_label(self._floor_code))
            if self._area_code:
                self.breadcrumbBar.addItem(
                    "area", self._area_names.get(self._area_code, self._area_code))
        self.breadcrumbBar.blockSignals(False)
        self._updateReturnButtonState()

    def _updateReturnButtonState(self):
        self.returnButton.setEnabled(
            self._last_shown_tab == self.ROUTE_SEATS and (
                bool(self._area_code) or bool(self._floor_code)))

    def _onReturnButtonClicked(self):
        if self._area_code:
            self._backToFloor()
        elif self._floor_code:
            self._backToFloors()
        else:
            self._updateReturnButtonState()

    def _onBreadcrumbChanged(self, route_key: str):
        if route_key == "area":
            return
        if route_key == "floor":
            self._backToFloor()
        elif route_key == self.ROUTE_SEATS:
            self._backToFloors()

    def _backToFloor(self):
        self._area_code = ""
        self.switchPage(self.floorMapPage)
        self._syncBreadcrumb()

    def _backToFloors(self):
        self._area_code = ""
        self._floor_code = ""
        self.switchPage(self.floorsPage)
        self._syncBreadcrumb()
        # 若进入其他校区楼层时切换过 rplace，返回时切回原校区
        if self._campus_switched and self._prev_campus:
            target = self._prev_campus
            self._campus_switched = False
            self._prev_campus = ""
            self._startJob(
                "library",
                self.tr("正在登录图书馆..."),
                lambda session, send_progress: (
                    send_progress(50, self.tr("正在恢复校区...")),
                    Library(session).switch_campus(target),
                )[1],
                lambda _ok: None,
            )

    # ======================== 线程 ========================

    def _startJob(self, site_key: str, message: str, worker, on_result):
        if self.thread_ is not None and self.thread_.isRunning():
            self.thread_.can_run = False
        started_uuid = getattr(accounts.current, "uuid", None)

        # worker 包装：向 worker 提供 send_progress(percent, msg)，
        # 按下阶段切到确定进度条并推进（对齐 EmptyRoomThread 的伪阶段进度）。
        def _wrapped(session):
            def send_progress(value: int, text: str):
                self.thread_.setIndeterminate.emit(False)
                self.thread_.progressChanged.emit(value)
                self.thread_.messageChanged.emit(text)
            return worker(session, send_progress)

        self.thread_ = CampusFeatureThread(
            site_key, message, _wrapped, need_login=True, parent=self)
        if self.processWidget:
            self.processWidget.deleteLater()
            self.processWidget = None
        self.processWidget = ProcessWidget(self.thread_, self.jobSlot, hide_on_end=True)
        self.jobLayout.addWidget(self.processWidget)

        def _guarded(payload):
            current = accounts.current
            if started_uuid is None or current is None or getattr(current, "uuid", None) != started_uuid:
                return
            on_result(payload)

        self.thread_.result.connect(_guarded)
        self.thread_.error.connect(self._onError)
        self.thread_.start()

    @pyqtSlot()
    def _onAccountChanged(self):
        if self.thread_ is not None and self.thread_.isRunning():
            self.thread_.can_run = False
        self._title_hidden = False
        self._floor_code = ""
        self._area_code = ""
        self._campus_switched = False
        self._prev_campus = ""
        self.bookingDetail.setText(self.tr("当前没有有效预约。"))
        self.bookingSeat.hide()
        self.switchPage(self.floorsPage)
        self._syncBreadcrumb()

    @pyqtSlot(str, str)
    def _onError(self, title: str, msg: str):
        self._info(InfoBar.error, title, msg)

    def _info(self, factory, title: str, msg: str) -> None:
        factory(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    # ======================== L2：楼层地图 ========================

    def _openFloorMap(self, floor_code: str):
        self._floor_code = floor_code
        self._area_code = ""
        self._syncBreadcrumb()
        self.switchPage(self.floorMapPage)
        self.floorMapView.set_plan(None, {}, {}, all_clickable=False)
        # 楼层所属校区（从楼层码前缀推断）
        prefix = re.match(r"([a-z]+)\d+floor", floor_code)
        target = PREFIX_CAMPUS_ID.get(prefix.group(1)) if prefix else ""
        self._startJob(
            "library",
            self.tr("正在登录图书馆..."),
            lambda session, send: self._load_floor_map(
                session, floor_code, target, send),
            self._onFloorMapLoaded,
        )

    @staticmethod
    def _load_floor_map(session, floor_code: str, target_campus: str, send_progress):
        lib = Library(session)
        switched, prev = False, ""
        current = lib.get_current_campus()
        if target_campus and current != target_campus:
            send_progress(0, "正在切换校区...")
            switched = lib.switch_campus(target_campus)
            prev = current
        try:
            send_progress(15, "正在获取楼层数据...")
            positions, status = lib.get_seat_layout(floor_code)
            send_progress(45, "正在加载楼层平面图...")
            image = lib.get_floor_image(floor_code)
            send_progress(75, "正在获取区域名称...")
            names = lib.get_area_names(floor_code)
            send_progress(100, "已就绪")
            return positions, status, image, names, switched, (prev if switched else current)
        except Exception:
            if switched and prev:
                try:
                    lib.switch_campus(prev)
                except Exception:
                    pass
            raise

    @pyqtSlot(object)
    def _onFloorMapLoaded(self, payload):
        positions, status, image, names, switched, prev = payload
        self._area_names = names or {}
        self._campus_switched = switched
        self._prev_campus = prev if switched else ""
        self.floorMapView.set_plan(
            {"base": image}, positions, status, all_clickable=True)

    # ======================== L3：区域座位 ========================

    def _openAreaMap(self, area_code: str):
        self._area_code = area_code
        self._syncBreadcrumb()
        self.switchPage(self.areaMapPage)
        self.areaMapView.set_plan(None, {}, {}, all_clickable=False)
        self._startJob(
            "library",
            self.tr("正在登录图书馆..."),
            lambda session, send: self._load_area(session, area_code, send),
            self._onAreaLoaded,
        )

    @staticmethod
    def _load_area(session, area_code: str, send_progress):
        lib = Library(session)
        send_progress(30, "正在获取座位数据...")
        positions, status = lib.get_seat_layout(area_code)
        send_progress(70, "正在加载区域平面图...")
        images = lib.get_floor_images(area_code)
        send_progress(100, "已就绪")
        return positions, status, images

    @pyqtSlot(object)
    def _onAreaLoaded(self, payload):
        positions, status, images = payload
        self.areaMapView.set_plan(images, positions, status)

    # ======================== 座位预约 ========================

    def _onSeatBookRequested(self, seat_id: str):
        area_code = self._area_code
        if not area_code:
            return
        box = MessageBox(
            self.tr("确认预约"),
            self.tr("预约座位 {0}？\n（若已有其它预约将自动换座）").format(seat_id),
            self.window())
        box.yesButton.setText(self.tr("确认预约"))
        box.cancelButton.setText(self.tr("取消"))
        if not box.exec_():
            return
        self._startJob(
            "library",
            self.tr("正在登录图书馆..."),
            lambda session, send_progress: (
                send_progress(50, self.tr("正在提交预约...")),
                Library(session).book_seat(seat_id, area_code),
            )[1],
            lambda result: self._onBooked(seat_id, area_code, result),
        )

    def _onBooked(self, seat_id: str, area_code: str, result):
        if result.success:
            self._info(InfoBar.success, self.tr("预约成功"), result.message)
            self._startJob(
                "library",
                self.tr("正在登录图书馆..."),
                lambda session, send: self._load_area(session, area_code, send),
                self._onAreaLoaded,
            )
        else:
            self._info(InfoBar.error, self.tr("预约失败"), result.message)

    # ======================== 我的预约 ========================

    def _refreshBooking(self):
        self.bookingDetail.setText(self.tr("加载中..."))
        self.bookingFail.setVisible(False)
        self._startJob(
            "library",
            self.tr("正在登录图书馆..."),
            lambda session, send_progress: (
                send_progress(50, self.tr("正在查询预约...")),
                Library(session).get_my_booking(),
            )[1],
            self._onBookingLoaded,
        )

    @pyqtSlot(object)
    def _booking_text_color(self) -> str:
        """显式按当前主题取文字色（暗色白 / 亮色黑），不依赖 qss/palette 传播。"""
        from qfluentwidgets import isDarkTheme
        return "#ffffff" if isDarkTheme() else "#202020"

    def _apply_booking_colors(self):
        color = self._booking_text_color()
        self.bookingSeat.setStyleSheet(f"color: {color};")
        self.bookingDetail.setStyleSheet(f"color: {color};")

    def _onBookingLoaded(self, booking):
        # 清理旧操作按钮 + 刷新主题色
        self._clear_booking_actions()
        self._apply_booking_colors()
        if booking is None:
            self.bookingSeat.hide()
            self.bookingDetail.setText(self.tr("当前没有有效预约。"))
            return
        self.bookingSeat.setText(
            self.tr("{0}").format(booking.seat_id))
        self.bookingSeat.show()
        parts = []
        if booking.area:
            parts.append(booking.area)
        if booking.status_text:
            parts.append(booking.status_text)
        self.bookingDetail.setText("　".join(parts) if parts else "")
        # 按预约状态生成操作按钮（取消/签到/离开/返回）
        self._booking_action_urls = dict(booking.action_urls)
        for label in ("取消预约", "入馆签到", "中途离开", "中途返回"):
            if label not in self._booking_action_urls:
                continue
            btn = PushButton(label, self.bookingPage)
            btn.setFixedWidth(110)
            btn.clicked.connect(
                lambda _=False, url=self._booking_action_urls[label], name=label
                : self._executeBookingAction(name, url))
            self.bookingActions.insertWidget(
                self.bookingActions.count() - 1, btn)

    def _clear_booking_actions(self):
        # 保留首尾 stretch，只删中间按钮
        while self.bookingActions.count() > 2:
            item = self.bookingActions.takeAt(self.bookingActions.count() - 2)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _executeBookingAction(self, label: str, url: str):
        box = MessageBox(
            self.tr("确认操作"),
            self.tr("确认{0}？").format(label),
            self.window())
        box.yesButton.setText(self.tr("确认"))
        box.cancelButton.setText(self.tr("取消"))
        if not box.exec_():
            return
        self._startJob(
            "library",
            self.tr("正在登录图书馆..."),
            lambda session, send_progress: (
                send_progress(50, self.tr("正在执行操作...")),
                Library(session).execute_action(url),
            )[1],
            lambda result: self._onBookingActionDone(result),
        )

    def _onBookingActionDone(self, result):
        if result.success:
            self._info(InfoBar.success, self.tr("操作成功"), result.message)
        else:
            self._info(InfoBar.error, self.tr("操作失败"), result.message)
        self._refreshBooking()