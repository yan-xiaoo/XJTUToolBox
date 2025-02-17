from PyQt5.QtCore import QThread, pyqtSignal

from app.utils import logger
from auth import get_session
from schedule.holiday import get_holiday_days


class HolidayThread(QThread):
    """
    请求节假日信息的线程
    """
    result = pyqtSignal(list)
    error = pyqtSignal(str, str)

    def run(self):
        try:
            data = get_holiday_days(get_session())
            self.result.emit(data)
        except Exception:
            logger.error("请求节假日信息失败：", exc_info=True)
            self.error.emit("", self.tr("获取节假日信息失败，请稍后重试"))
