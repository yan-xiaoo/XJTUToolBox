from PyQt5.QtCore import QThread, pyqtSignal

from schedule.holiday import get_holiday_days


class HolidayThread(QThread):
    """
    请求节假日信息的线程
    """
    result = pyqtSignal(list)

    def run(self):
        data = get_holiday_days()
        self.result.emit(data)
