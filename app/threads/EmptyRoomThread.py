from typing import Optional, List

import requests
from PyQt5.QtCore import pyqtSignal

from auth import EHALL_LOGIN_URL, ServerError
from auth.new_login import NewLogin
from ehall.empty_room import EmptyRoom
from ..sessions.ehall_session import EhallSession
from ..threads.ProcessWidget import ProcessThread
from ..utils import accounts, logger, cfg
from ..utils.cache import CacheManager


class EmptyRoomThread(ProcessThread):
    """
    获得空闲教室相关信息的线程
    """
    result = pyqtSignal(dict)
    success = pyqtSignal(str, str)

    def __init__(self, campus_name=None, building_names: Optional[List[str]] = None, date=None, parent=None):
        super().__init__(parent)

        self.campus_name = campus_name
        self.building_names = building_names
        self.date = date
        self.util = None

    @property
    def session(self) -> EhallSession:
        """
        获得当前账户访问 ehall 的 session
        """
        return accounts.current.session_manager.get_session("ehall")

    def login(self):
        """
        使当前账户的 session 登录 ehall
        """
        self.setIndeterminate.emit(True)
        self.messageChanged.emit(self.tr("正在登录 EHALL..."))
        self.session.login(accounts.current.username, accounts.current.password)
        if not self.can_run:
            return False
        # 进入课表页面
        self.util = EmptyRoom(self.session)
        self.setIndeterminate.emit(False)
        self.progressChanged.emit(90)

        return True

    def run(self):
        # 强制重置可运行状态
        self.can_run = True
        # 判断当前是否存在账户
        if accounts.current is None:
            self.error.emit(self.tr("未登录"), self.tr("请先添加一个账户"))
            self.canceled.emit()
            return

        try:
            # 如果当前账户已经登录，重建代理对象，防止出现 util 和 session 不对应的情况。
            if self.session.has_login:
                self.util = EmptyRoom(self.session)
            else:
                # 手动登录。虽然 EhallSession 有自动登录功能，但是为了显示进度条，还是一步一步手动登录。
                result = self.login()
                if not result:
                    self.canceled.emit()
                    return

            cache_manager = CacheManager()

            self.progressChanged.emit(95)
            self.messageChanged.emit(self.tr("正在获得校区代码"))
            campus_cache = cache_manager.read_expire_json("empty_room_campus_code.json", 7)
            if campus_cache is not None:
                # 如果缓存中存在校区代码，则直接使用缓存中的数据
                campus_code_dict = campus_cache
            else:
                campus_code_dict = self.util.getCampusCode()
                cache_manager.write_expire_json("empty_room_campus_code.json", campus_code_dict, True)
            try:
                campus_code = campus_code_dict[self.campus_name]
            except KeyError:
                self.error.emit("", self.tr("未知校区：") + self.campus_name)
                self.canceled.emit()
                return
            if not self.can_run:
                self.canceled.emit()
                return

            self.progressChanged.emit(100)
            self.messageChanged.emit(self.tr("正在获得教学楼代码"))
            # 如果缓存中存在教学楼代码，则直接使用缓存中的数据
            building_cache = cache_manager.read_expire_json("empty_room_building_code.json", 7)
            if building_cache is not None:
                # 如果缓存中存在教学楼代码，则直接使用缓存中的数据
                building_code_dict = building_cache
            else:
                building_code_dict = self.util.getBuildingCode()
                cache_manager.write_expire_json("empty_room_building_code.json", building_code_dict, True)
            building_codes = []
            for building in self.building_names:
                try:
                    building_codes.append(building_code_dict[building])
                except KeyError:
                    self.error.emit("", self.tr("未知教学楼：") + self.campus_name)
                    self.canceled.emit()
                    return
            if not self.can_run:
                self.canceled.emit()
                return

            # 如果缓存中存在数据，则直接使用缓存中的数据
            data_diction = cache_manager.read_expire_json(f"empty_room_result_{self.date}.json", 7)
            if data_diction is not None:
                pass

            result_diction = {}
            total_progress = 11 * len(building_codes)

            cache_diction = {}

            for i, building_code in enumerate(building_codes):
                # 通过传入错误的数据，获得全楼所有的教室
                if not self.can_run:
                    self.canceled.emit()
                    return
                cache_diction[building_code] = {}
                if data_diction is not None and building_code in data_diction:
                    # 如果缓存中存在数据，则直接使用缓存中的数据
                    cache_diction[building_code] = data_diction[building_code]
                    all_classroom = cache_diction[building_code]['0']
                else:
                    all_classroom = self.util.getEmptyRoom(campus_code, building_code, self.date, 0, 0)

                for one_classroom in all_classroom:
                    result_diction[one_classroom["name"]] = {"status": [1 for _ in range(11)], "size": one_classroom["capacity"]}

                cache_diction[building_code]['0'] = all_classroom

                for period in range(1, 12):
                    self.progressChanged.emit(int((i * 12 + period) / total_progress * 100))
                    self.messageChanged.emit(self.tr(self.tr("正在获取 ") + self.building_names[i] + self.tr(" 教学楼第 ") + str(period) + " 节的空闲信息"))
                    if data_diction is not None and building_code in data_diction and str(period) in data_diction[building_code]:
                        # 如果缓存中存在数据，则直接使用缓存中的数据
                        single_result = data_diction[building_code][str(period)]
                    else:
                        single_result = self.util.getEmptyRoom(campus_code, building_code, self.date, period, period)
                    if not self.can_run:
                        self.canceled.emit()
                        return
                    cache_diction[building_code][str(period)] = single_result

                    for single in single_result:
                        if single["name"] in result_diction:
                            result_diction[single["name"]]["status"][period - 1] = 0

        except ServerError as e:
            logger.error("服务器错误", exc_info=True)
            if e.code == 102:
                self.error.emit(self.tr("登录问题"), self.tr("需要进行两步验证，请前往账户界面，选择对应账户进行验证。"))
                accounts.current.MFASignal.emit(True)
            else:
                self.error.emit(self.tr("服务器错误"), e.message)
            self.canceled.emit()
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
            cache_manager.write_expire_json(f"empty_room_result_{self.date}.json", cache_diction, True)
            self.success.emit("", self.tr("查询成功"))
            self.result.emit(result_diction)
            self.hasFinished.emit()
