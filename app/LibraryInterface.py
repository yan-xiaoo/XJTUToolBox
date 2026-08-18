from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import BodyLabel, CheckBox, ComboBox, PrimaryPushButton, PushButton

from library import AREA_MAP, FLOORS, Library
from .components.CampusPage import CampusPage
from .utils import accounts


class LibraryInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("libraryInterface", "图书馆座位", "查空座、预约、换座、取消与签到", parent)
        self.seats = []
        self.booking = None
        self._booking_loaded = False

        self.floorBox = ComboBox(self.view)
        self.areaBox = ComboBox(self.view)
        self.areaBox.setMinimumWidth(220)
        for floor in FLOORS:
            self.floorBox.addItem(floor)
        self.floorBox.currentTextChanged.connect(self._reload_areas)
        self._reload_areas(self.floorBox.currentText())
        self.freeOnly = CheckBox(self.tr("只看空闲"), self.view)
        self.freeOnly.setChecked(True)
        self.freeOnly.stateChanged.connect(self._render_seats)
        self.queryButton = PrimaryPushButton(self.tr("查询座位"), self.view)
        self.queryButton.clicked.connect(self.query_seats)
        self.add_toolbar(
            self.labeled(self.tr("楼层"), self.floorBox),
            self.labeled(self.tr("区域"), self.areaBox, width=40),
            self.freeOnly,
            self.queryButton,
        )

        self.bookingLabel = BodyLabel(self.tr("打开本页会自动查询当前预约。"), self.view)
        self.bookingLabel.setWordWrap(True)
        self.vBoxLayout.addWidget(self.bookingLabel)

        self.bookButton = PrimaryPushButton(self.tr("预约选中座位"), self.view)
        self.refreshBookButton = PushButton(self.tr("刷新预约"), self.view)
        self.checkinButton = PushButton(self.tr("入馆签到"), self.view)
        self.leaveButton = PushButton(self.tr("中途离开"), self.view)
        self.returnButton = PushButton(self.tr("中途返回"), self.view)
        self.cancelButton = PushButton(self.tr("取消预约"), self.view)
        self.bookButton.clicked.connect(self.book_selected)
        self.refreshBookButton.clicked.connect(self.refresh_booking)
        self.cancelButton.clicked.connect(lambda: self.run_action("取消预约"))
        self.checkinButton.clicked.connect(lambda: self.run_action("入馆签到"))
        self.leaveButton.clicked.connect(lambda: self.run_action("中途离开"))
        self.returnButton.clicked.connect(lambda: self.run_action("中途返回"))
        self.add_toolbar(
            self.bookButton,
            self.refreshBookButton,
            self.checkinButton,
            self.leaveButton,
            self.returnButton,
            self.cancelButton,
        )
        self._sync_actions()

        self.table = self.make_table([self.tr("座位"), self.tr("状态")])
        self.table.doubleClicked.connect(self.book_selected)
        self.vBoxLayout.addWidget(self.table, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._booking_loaded or accounts.current is None:
            return
        self._booking_loaded = True
        self.refresh_booking()

    def _reload_areas(self, floor: str):
        self.areaBox.clear()
        for name in FLOORS.get(floor, []):
            self.areaBox.addItem(name, userData=AREA_MAP.get(name))

    def _sync_actions(self):
        actions = self.booking.action_urls if self.booking else {}
        self.checkinButton.setEnabled("入馆签到" in actions)
        self.leaveButton.setEnabled("中途离开" in actions)
        self.returnButton.setEnabled("中途返回" in actions)
        self.cancelButton.setEnabled("取消预约" in actions)

    def query_seats(self):
        if not self.require_account():
            return
        area_code = self.areaBox.currentData()
        if not area_code:
            self.warn(self.tr("未选择区域"), self.tr("请先选择楼层和区域"))
            return
        self.start_job("library", self.tr("正在查询座位..."), lambda session: Library(session).get_seats(area_code), self._on_seats)

    def _on_seats(self, payload):
        seats, stats = payload
        self.seats = seats
        self._render_seats()
        area_code = self.areaBox.currentData()
        stat = stats.get(area_code)
        extra = f" {stat.available}/{stat.total}" if stat else ""
        self.success(self.tr("查询成功"), self.tr("空闲 {count} 个{extra}").format(
            count=sum(1 for seat in seats if seat.available), extra=extra,
        ))

    def _render_seats(self):
        rows = [seat for seat in self.seats if seat.available] if self.freeOnly.isChecked() else self.seats
        self.table.setRowCount(len(rows))
        for row, seat in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(seat.seat_id))
            self.table.setItem(row, 1, QTableWidgetItem(self.tr("空闲") if seat.available else self.tr("占用")))
        self._visible_seats = rows

    def _selected_seat(self):
        row = self.table.currentRow()
        seats = getattr(self, "_visible_seats", self.seats)
        if row < 0 or row >= len(seats):
            return None
        return seats[row]

    def book_selected(self):
        if not self.require_account():
            return
        seat = self._selected_seat()
        if seat is None:
            self.warn(self.tr("未选择座位"), self.tr("请先在表格中选择座位"))
            return
        if not seat.available:
            self.warn(self.tr("座位占用"), self.tr("请选择空闲座位"))
            return
        area_code = self.areaBox.currentData()
        self.start_job(
            "library",
            self.tr("正在预约座位..."),
            lambda session: Library(session).book_seat(seat.seat_id, area_code),
            self._on_book,
        )

    def _on_book(self, result):
        if result.success:
            self.success(self.tr("预约成功"), result.message)
            self.refresh_booking()
        else:
            self.warn(self.tr("预约失败"), result.message)

    def refresh_booking(self):
        if not self.require_account():
            return
        self.start_job("library", self.tr("正在查询预约..."), lambda session: Library(session).get_my_booking(), self._on_booking)

    def _on_booking(self, booking):
        self.booking = booking
        self._sync_actions()
        if booking is None:
            self.bookingLabel.setText(self.tr("当前没有有效预约"))
            return
        self.bookingLabel.setText(
            self.tr("当前预约：{seat}  {area}  {status}").format(
                seat=booking.seat_id, area=booking.area, status=booking.status_text,
            )
        )

    def run_action(self, label: str):
        if not self.require_account():
            return
        if not self.booking or label not in self.booking.action_urls:
            self.warn(self.tr("无法操作"), self.tr("请先刷新预约，或当前预约没有该操作"))
            return
        url = self.booking.action_urls[label]
        self.start_job("library", self.tr("正在执行操作..."), lambda session: Library(session).execute_action(url), self._on_book)
