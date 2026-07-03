from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QComboBox, QSizePolicy, QPushButton
from qfluentwidgets import (ScrollArea, TitleLabel, StrongBodyLabel, SimpleCardWidget,
                            BodyLabel, CaptionLabel, FluentIcon, IconWidget, FlowLayout,
                            PrimaryPushButton, InfoBar, InfoBarPosition)

from .utils import StyleSheet, accounts
from .sessions.venue_session import VenueSession
from .venues.venue import VenueUtil, VenueInfo, AreaSlot


class _VenueCard(SimpleCardWidget):
    """场馆选择卡片。"""
    clicked = pyqtSignal(VenueInfo)

    def __init__(self, venue: VenueInfo, parent=None):
        super().__init__(parent)
        self.venue = venue
        self.setFixedWidth(370)
        self.setMinimumHeight(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        icon = IconWidget(FluentIcon.LOCATION, self)
        icon.setFixedSize(32, 32)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        name = BodyLabel(venue.name, self)
        name.setWordWrap(True)
        vbox.addWidget(name)
        if venue.address:
            addr = CaptionLabel(venue.address, self)
            addr.setTextColor("#606060", "#d2d2d2")
            vbox.addWidget(addr)
        vbox.addStretch(1)

        layout.addWidget(icon, 0, Qt.AlignVCenter)
        layout.addLayout(vbox, stretch=1)

    def mouseReleaseEvent(self, event):
        self.clicked.emit(self.venue)
        super().mouseReleaseEvent(event)


class _SlotCard(SimpleCardWidget):
    """时段展示卡片。"""

    def __init__(self, slot: AreaSlot, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setMinimumHeight(60)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(2)

        time_label = BodyLabel(slot.time_slot, self)
        vbox.addWidget(time_label)

        info = f"{slot.area_name}  ¥{slot.price:.0f}"
        if not slot.is_available:
            info += "（已占用）"
        elif slot.using_num > 0:
            info += f"（{slot.using_num}/{slot.all_count}）"

        detail = CaptionLabel(info, self)
        detail.setTextColor("#606060", "#d2d2d2")
        vbox.addWidget(detail)
        vbox.addStretch(1)


class VenueInterface(ScrollArea):
    """体育场馆预约界面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VenueInterface")
        self._util: Optional[VenueUtil] = None

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        self.titleLabel = TitleLabel(self.tr("体育场馆"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.subtitleLabel = StrongBodyLabel(
            self.tr("选择场馆和日期，查看可预订时段"), self.view)
        self.subtitleLabel.setContentsMargins(15, 5, 0, 0)
        self.vBoxLayout.addWidget(self.subtitleLabel)

        spacer = QWidget(self.view)
        spacer.setFixedHeight(10)
        self.vBoxLayout.addWidget(spacer)

        # ---- 控制栏 ----
        self.controlBar = QFrame(self.view)
        self.controlLayout = QHBoxLayout(self.controlBar)
        self.controlLayout.setContentsMargins(0, 0, 0, 0)
        self.controlLayout.setSpacing(12)

        self.dateCombo = QComboBox(self.controlBar)
        self.dateCombo.setMinimumWidth(150)
        self.dateCombo.currentIndexChanged.connect(self._onDateChanged)
        self.refreshBtn = PrimaryPushButton(FluentIcon.SYNC, self.tr("刷新"), self.controlBar)
        self.refreshBtn.clicked.connect(self._refresh)

        self.controlLayout.addWidget(StrongBodyLabel(self.tr("日期："), self.controlBar))
        self.controlLayout.addWidget(self.dateCombo)
        self.controlLayout.addStretch(1)
        self.controlLayout.addWidget(self.refreshBtn)
        self.vBoxLayout.addWidget(self.controlBar)

        # ---- 场馆列表区域 ----
        self.venueLabel = StrongBodyLabel(self.tr("场馆"), self.view)
        self.venueLabel.setContentsMargins(0, 12, 0, 4)
        self.vBoxLayout.addWidget(self.venueLabel)

        self.venueHost = QWidget(self.view)
        self.venueFlow = FlowLayout(self.venueHost, needAni=False)
        self.venueFlow.setVerticalSpacing(12)
        self.venueFlow.setHorizontalSpacing(12)
        self.vBoxLayout.addWidget(self.venueHost)

        # ---- 时段区域 ----
        self.slotLabel = StrongBodyLabel(self.tr("可预订时段"), self.view)
        self.slotLabel.setContentsMargins(0, 12, 0, 4)
        self.slotLabel.setVisible(False)
        self.vBoxLayout.addWidget(self.slotLabel)

        self.slotHost = QWidget(self.view)
        self.slotFlow = FlowLayout(self.slotHost, needAni=False)
        self.slotFlow.setVerticalSpacing(10)
        self.slotFlow.setHorizontalSpacing(10)
        self.vBoxLayout.addWidget(self.slotHost)

        # ---- 初始化 ----
        self._selected_venue: Optional[VenueInfo] = None
        self._setup_dates()
        accounts.currentAccountChanged.connect(self._onAccountChanged)

        StyleSheet.LMS_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setMinimumWidth(450)

    def _setup_dates(self):
        """初始化日期选择。"""
        from datetime import date as dt, timedelta
        today = dt.today()
        self.dateCombo.clear()
        for i in range(7):
            d = today + timedelta(days=i)
            label = f"{d.isoformat()}（{'今天' if i == 0 else f'周{['一','二','三','四','五','六','日'][d.weekday()]}' if i < 7 else ''}）"
            self.dateCombo.addItem(label, d.isoformat())

    def _ensure_login(self) -> bool:
        """确保场馆登录。"""
        current = accounts.current
        if current is None:
            InfoBar.error(self.tr("未登录"), self.tr("请先添加一个账户"), parent=self.window())
            return False
        try:
            session = current.session_manager.get_session("venue")
            session.ensure_login(
                current.username,
                current.password,
                account=current,
                mfa_provider=current.session_manager.mfa_provider,
                allow_qrcode_login=False,
            )
        except Exception as e:
            InfoBar.error(self.tr("登录失败"), str(e), parent=self.window())
            return False
        self._util = VenueUtil(session)
        return True

    def _load_venues(self):
        """加载场馆列表。"""
        if self._util is None:
            return
        try:
            venues = self._util.get_venues()
        except Exception as e:
            InfoBar.error(self.tr("加载失败"), str(e), parent=self.window())
            return

        # 清空已有卡片
        while self.venueFlow.count():
            item = self.venueFlow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for venue in venues:
            card = _VenueCard(venue, self.venueHost)
            card.clicked.connect(self._onVenueSelected)
            self.venueFlow.addWidget(card)

        InfoBar.success(self.tr("加载完成"),
                        self.tr("共 {0} 个场馆").format(len(venues)),
                        position=InfoBarPosition.TOP_RIGHT,
                        parent=self.window())

    def _onVenueSelected(self, venue: VenueInfo):
        """选择场馆，加载时段。"""
        self._selected_venue = venue
        self._load_slots()

    def _load_slots(self):
        """加载选中场馆的时段。"""
        while self.slotFlow.count():
            item = self.slotFlow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._selected_venue is None or self._util is None:
            self.slotLabel.setVisible(False)
            return

        date_str = self.dateCombo.currentData()
        try:
            ok_slots = self._util.get_available_slots(self._selected_venue.id, date_str)
            locked_slots = self._util.get_locked_slots(self._selected_venue.id, date_str)
        except Exception as e:
            InfoBar.error(self.tr("加载时段失败"), str(e), parent=self.window())
            return

        self.slotLabel.setVisible(True)
        self.slotLabel.setText(self.tr("可预订时段 —— {0}").format(self._selected_venue.name))

        all_slots = ok_slots + locked_slots
        if all_slots:
            for s in all_slots:
                card = _SlotCard(s, self.slotHost)
                self.slotFlow.addWidget(card)
        else:
            empty = BodyLabel(self.tr("暂无可用时段"), self.slotHost)
            self.slotFlow.addWidget(empty)

        InfoBar.success(self.tr("时段已更新"),
                        self.tr("可用 {0} / 已占用 {1}").format(len(ok_slots), len(locked_slots)),
                        position=InfoBarPosition.TOP_RIGHT,
                        parent=self.window())

    def _onDateChanged(self):
        """日期切换时重新加载时段。"""
        if self._selected_venue:
            self._load_slots()

    def _refresh(self):
        """刷新场馆和时段。"""
        if not self._ensure_login():
            return
        self._load_venues()
        if self._selected_venue:
            self._load_slots()

    def _onAccountChanged(self):
        """切换账号时重置。"""
        self._util = None
        self._selected_venue = None
        while self.venueFlow.count():
            item = self.venueFlow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self.slotFlow.count():
            item = self.slotFlow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.slotLabel.setVisible(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().setValue(0)
