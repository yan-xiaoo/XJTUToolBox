from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QTableWidgetItem
from qfluentwidgets import BodyLabel, CalendarPicker, PrimaryPushButton

from card import CampusCard
from .components.CampusPage import CampusPage
from .utils import accounts


class CampusCardInterface(CampusPage):
    def __init__(self, parent=None):
        super().__init__("campusCardInterface", "校园卡", "查询余额与消费流水", parent)
        self._auto_loaded = False

        self.summary = BodyLabel(self.tr("打开本页会自动查询最近流水。"), self.view)
        self.summary.setWordWrap(True)
        self.vBoxLayout.addWidget(self.summary)

        self.fromPicker = CalendarPicker(self.view)
        self.toPicker = CalendarPicker(self.view)
        self.toPicker.setDate(QDate.currentDate())
        self.fromPicker.setDate(QDate.currentDate().addDays(-90))
        self.refreshButton = PrimaryPushButton(self.tr("查询"), self.view)
        self.refreshButton.setFixedWidth(96)
        self.refreshButton.clicked.connect(self.refresh)
        self.add_toolbar(
            self.labeled(self.tr("开始"), self.fromPicker, width=40),
            self.labeled(self.tr("结束"), self.toPicker, width=40),
            self.refreshButton,
        )

        self.table = self.make_table([
            self.tr("时间"), self.tr("商户"), self.tr("类型"), self.tr("金额"), self.tr("余额"),
        ])
        self.vBoxLayout.addWidget(self.table, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_loaded or accounts.current is None:
            return
        self._auto_loaded = True
        self.refresh()

    def refresh(self):
        if not self.require_account():
            return
        start = self.fromPicker.getDate().toPyDate()
        end = self.toPicker.getDate().toPyDate()

        def worker(session):
            util = CampusCard(session)
            info = util.get_card_info()
            total, records = util.get_transactions(start, end, page=1, page_size=80)
            return info, total, records

        self.start_job("campus_card", self.tr("正在登录校园卡..."), worker, self._on_result)

    def _on_result(self, payload):
        info, total, records = payload
        status = []
        if info.lost:
            status.append(self.tr("已挂失"))
        if info.frozen:
            status.append(self.tr("已冻结"))
        extra = f"（{' / '.join(status)}）" if status else ""
        self.summary.setText(
            self.tr("{name}  {sno}  余额 {balance:.2f} 元  未结算 {pending:.2f} 元  共 {total} 笔{extra}").format(
                name=info.name, sno=info.student_no, balance=info.balance,
                pending=info.pending_amount, total=total, extra=extra,
            )
        )
        self.table.setRowCount(len(records))
        for row, item in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(item.time))
            self.table.setItem(row, 1, QTableWidgetItem(item.merchant))
            self.table.setItem(row, 2, QTableWidgetItem(item.type_name))
            self.table.setItem(row, 3, QTableWidgetItem(f"{item.amount:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{item.balance:.2f}"))
        self.success(self.tr("查询成功"), self.tr("已更新校园卡流水"))
