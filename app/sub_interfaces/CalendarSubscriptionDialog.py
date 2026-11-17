from PyQt5.QtNetwork import QNetworkInterface, QAbstractSocket
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QApplication
from qfluentwidgets import BodyLabel, ComboBox, SpinBox, CheckBox, LineEdit, PushButton, isDarkTheme, qconfig

from schedule.calendar_subscription import is_lan_address


class CalendarSubscriptionDialog(QDialog):
    def __init__(self, interface):
        super().__init__(interface)
        self.interface = interface
        self.setWindowTitle(self.tr("局域网日历订阅"))
        self.setMinimumWidth(580)
        self._applyTheme()
        qconfig.themeChangedFinished.connect(self._applyTheme)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.hint = BodyLabel(self.tr(
            "同一局域网内可通过链接读取本机课表，电脑和工具箱需保持运行。\n"
            "链接持有人可查看课程、地点和考试；请只在可信网络开启。\n"
            "使用 HTTP，不支持要求公网 HTTPS 的云端订阅服务。\n"
            "重启后需手动开启；地址和端口不变时可沿用原链接。"), self)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        row = QHBoxLayout()
        self.address = ComboBox(self)
        addresses = sorted({a.toString() for a in QNetworkInterface.allAddresses()
                            if a.protocol() == QAbstractSocket.IPv4Protocol
                            and is_lan_address(a.toString()) and not a.isLoopback()})
        self.address.addItems(addresses or ["127.0.0.1"])
        row.addWidget(BodyLabel(self.tr("本机地址"), self))
        row.addWidget(self.address)
        self.port = SpinBox(self)
        self.port.setRange(1024, 65535)
        self.port.setValue(8765)
        row.addWidget(BodyLabel(self.tr("端口"), self))
        row.addWidget(self.port)
        layout.addLayout(row)
        self.alarm = CheckBox(self.tr("设置课程和考试提醒"), self)
        self.alarm.setChecked(True)
        self.holiday = CheckBox(self.tr("忽略已缓存的节假日课程（无缓存时请先导出一次 ICS）"), self)
        layout.addWidget(self.alarm)
        layout.addWidget(self.holiday)
        self.link = LineEdit(self)
        self.link.setReadOnly(True)
        layout.addWidget(self.link)
        self.status = BodyLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.toggle = PushButton(self)
        self.copy = PushButton(self.tr("复制订阅链接"), self)
        close = PushButton(self.tr("关闭窗口"), self)
        buttons.addWidget(self.toggle)
        buttons.addWidget(self.copy)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.toggle.clicked.connect(self._toggle)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.link.text()))
        close.clicked.connect(self.accept)
        interface.calendarSubscriptionChanged.connect(self._sync)
        self.finished.connect(lambda: interface.calendarSubscriptionChanged.disconnect(self._sync))
        self._sync()

    def _applyTheme(self):
        color = "#202020" if isDarkTheme() else "#f9f9f9"
        self.setStyleSheet(f"QDialog {{ background-color: {color}; }}")

    def _sync(self):
        active = self.interface.calendar_subscription.running
        self.link.setText(self.interface.calendar_subscription.url or "")
        self.toggle.setText(self.tr("停止订阅") if active else self.tr("开启订阅"))
        self.copy.setEnabled(active)
        for widget in (self.address, self.port, self.alarm, self.holiday):
            widget.setEnabled(not active)
        self.status.setText(self.tr("已开启；课表变动后更新本地内容，设备刷新频率由日历客户端决定")
                            if active else self.tr("未开启；127.0.0.1 仅限本机，其他设备需选择局域网地址并允许防火墙访问"))

    def _toggle(self):
        try:
            if self.interface.calendar_subscription.running:
                self.interface.stopCalendarSubscription()
            else:
                self.interface.startCalendarSubscription(self.address.currentText(), self.port.value(),
                    self.holiday.isChecked(), self.alarm.isChecked())
            self._sync()
        except Exception as error:
            self.status.setText(str(error))
