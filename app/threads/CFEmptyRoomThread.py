import datetime
from typing import Optional, List

import requests
from PyQt5.QtCore import pyqtSignal

from ..threads.ProcessWidget import ProcessThread
from ..utils import logger
from ..utils.cache import CacheManager


class CFEmptyRoomThread(ProcessThread):
    """
    从 Cloudflare 获得空闲教室相关信息的线程
    """
    result = pyqtSignal(dict)
    success = pyqtSignal(str, str)

    def __init__(self, campus_name=None, building_names: Optional[List[str]] = None, date: datetime.date=None, parent=None):
        super().__init__(parent)

        self.campus_name = campus_name
        self.building_names = building_names
        self.date = date
        self.util = None

    def run(self):
        # 强制重置可运行状态
        self.can_run = True
        self.messageChanged.emit(self.tr("正在从 Cloudflare CDN 获取数据..."))
        self.progressChanged.emit(10)
        try:
            cache_manager = CacheManager()
            data = cache_manager.read_expire_json(f"empty_room_cloudflare_{self.date}.json", 1)
            if data is None:
                response = requests.get("https://gh-release.xjtutoolbox.com/",
                                    params={"file": f"static/empty_room/{self.date.isoformat()}.json"})
                if response.status_code == 404:
                    self.error.emit("无数据", self.tr("当天暂无空闲教室数据，请稍后再试。"))
                    self.canceled.emit()
                    return
                response.raise_for_status()
                data = response.json()

            self.progressChanged.emit(80)
            self.messageChanged.emit(self.tr("正在生成结果..."))
            cache_manager.write_expire_json(f"empty_room_cloudflare_{self.date}.json", data, True)

            result = {}
            for name in self.building_names:
                if name not in data.get(self.campus_name, {}):
                    self.error.emit("无数据", self.tr(f"当天暂无 {self.campus_name} - {name} 的空闲教室数据，请稍后再试。"))
                    self.canceled.emit()
                    return

                for one_classroom in data[self.campus_name][name]:
                    result[one_classroom] = data[self.campus_name][name][one_classroom]

            self.progressChanged.emit(100)

        except requests.ConnectionError:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("无网络连接"), self.tr("请检查网络连接，然后重试。"))
            self.canceled.emit()
        except requests.RequestException as e:
            logger.error("网络错误", exc_info=True)
            self.error.emit(self.tr("网络错误"), str(e))
            self.canceled.emit()
        except Exception as e:
            logger.error("其他错误", exc_info=True)
            self.error.emit(self.tr("其他错误"), str(e))
            self.canceled.emit()
        else:
            self.success.emit("", self.tr("查询成功"))
            self.result.emit(result)
            self.hasFinished.emit()
