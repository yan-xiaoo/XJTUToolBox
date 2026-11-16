import json
from types import SimpleNamespace
from PyQt5.QtCore import pyqtSignal
from .ManagedTaskThread import ManagedTaskThread

from app.utils import logger
from auth import get_session
from schedule.holiday import get_holiday_days


class HolidayThread(ManagedTaskThread):
    """
    请求节假日信息的线程
    """
    result = pyqtSignal(list)
    error = pyqtSignal(str, str)

    def run(self):
        try:
            with get_session() as session:
                # The source functions accept a requests-shaped object. Bound
                # each socket read and check cancellation between chunks.
                def get(url):
                    if self._cancel.is_set():
                        raise RuntimeError('holiday request cancelled')
                    with session.get(url, timeout=(5, 10), stream=True) as response:
                        response.raise_for_status()
                        chunks, size = [], 0
                        while not self._cancel.is_set():
                            chunk = response.raw.read1(65536, decode_content=True)
                            if not chunk:
                                return SimpleNamespace(json=lambda: json.loads(b''.join(chunks)))
                            size += len(chunk)
                            if size > 4 * 1024 * 1024:
                                raise ValueError('holiday response too large')
                            chunks.append(chunk)
                        raise RuntimeError('holiday request cancelled')
                data = get_holiday_days(SimpleNamespace(get=get))
            if not self._cancel.is_set():
                self.result.emit(data)
        except Exception:
            if not self._cancel.is_set():
                logger.error("请求节假日信息失败：", exc_info=True)
                self.error.emit("", self.tr("获取节假日信息失败，请稍后重试"))
