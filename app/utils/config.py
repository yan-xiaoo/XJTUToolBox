import datetime
import os

from packaging.version import parse
from qfluentwidgets import QConfig, qconfig, OptionsConfigItem, OptionsValidator, ConfigSerializer, Theme, \
    EnumSerializer, ConfigValidator
from enum import Enum
from .migrate_data import DATA_DIRECTORY


class BooleanSerializer(ConfigSerializer):
    def serialize(self, value):
        return value

    def deserialize(self, value):
        return bool(value)


class TimeValidator(ConfigValidator):
    def __init__(self, default=datetime.time(hour=18, minute=0)):
        super().__init__()
        self.default = default

    def validate(self, value):
        return isinstance(value, datetime.time)

    def correct(self, value):
        return value if self.validate(value) else self.default


class TimeSerializer(ConfigSerializer):
    def serialize(self, value):
        return value.strftime("%H:%M")

    def deserialize(self, value):
        try:
            hour, minute = map(int, value.split(":"))
            return datetime.time(hour=hour, minute=minute)
        except ValueError:
            return datetime.time(hour=18, minute=0)


class DateTimeValidator(ConfigValidator):
    def __init__(self, default=datetime.datetime(1970, 1, 1)):
        super().__init__()
        self.default = default

    def validate(self, value):
        return isinstance(value, datetime.datetime)

    def correct(self, value):
        return value if self.validate(value) else self.default


class DateTimeSerializer(ConfigSerializer):
    def serialize(self, value):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def deserialize(self, value):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.datetime(1970, 1, 1)


class AttendanceLoginMethod(Enum):
    # 不设置，每次询问
    NONE = 0
    # 直接登录
    NORMAL = 1
    # WebVPN 登录
    WEBVPN = 2


class TraySetting(Enum):
    # 未设置，需要询问
    UNKNOWN = 0
    # 直接关闭程序
    QUIT = 1
    # 最小化到托盘
    MINIMIZE = 2


class Config(QConfig):
    AttendanceLoginMethod = AttendanceLoginMethod

    hasReadLoginTip = OptionsConfigItem("one_time_notice", "read_login_tip", False,
                                        OptionsValidator([True, False]), BooleanSerializer())
    defaultAttendanceLoginMethod = OptionsConfigItem("Settings", "default_attendance_login_method",
                                                     AttendanceLoginMethod.NONE,
                                                     OptionsValidator(
                                                         [AttendanceLoginMethod.NONE, AttendanceLoginMethod.NORMAL,
                                                          AttendanceLoginMethod.WEBVPN]),
                                                     EnumSerializer(AttendanceLoginMethod))
    checkUpdateAtStartTime = OptionsConfigItem("Settings", "check_update_at_start_time",
                                               True, OptionsValidator([True, False]), BooleanSerializer())
    prereleaseEnable = OptionsConfigItem("Settings", "prerelease_enable",
                                         False, OptionsValidator([True, False]), BooleanSerializer())
    ignoreLateCourse = OptionsConfigItem("Settings", "ignore_late_course",
                                         True, OptionsValidator([True, False]), BooleanSerializer())
    autoRetryAttendance = OptionsConfigItem("Settings", "auto_retry_attendance",
                                            True, OptionsValidator([True, False]), BooleanSerializer())
    openExternalBrowser = OptionsConfigItem("Settings", "open_external_browser",
                                       False, OptionsValidator([True, False]), BooleanSerializer())
    traySetting = OptionsConfigItem("Settings", "tray_setting",
                                    TraySetting.UNKNOWN,
                                    OptionsValidator([TraySetting.UNKNOWN, TraySetting.QUIT, TraySetting.MINIMIZE]),
                                    EnumSerializer(TraySetting))
    noticeAutoSearch = OptionsConfigItem("Settings", "notice_auto_search",
                          False, OptionsValidator([True, False]), BooleanSerializer())
    noticeSearchTime = OptionsConfigItem("Settings", "notice_search_time",
                                         datetime.time(hour=18, minute=0), TimeValidator(), TimeSerializer())
    # 这其实不是个设置项目，只是用来存储上次搜索的时间
    lastSearchTime = OptionsConfigItem("Settings", "last_search_time",
                                         datetime.datetime(1970, 1, 1), DateTimeValidator(),
                                         DateTimeSerializer())

    def __init__(self):
        super().__init__()

        try:
            with open("./assets/version.txt", "r", encoding="utf-8") as f:
                self.version = parse(f.read().strip())
        except (FileNotFoundError, ValueError):
            # 找不到版本文件或者文件错误的话，通过设置一个不可能的版本号来禁止更新
            self.version = parse("99.99.99")


DEFAULT_CONFIG_PATH = os.path.join(DATA_DIRECTORY, "config.json")


cfg = Config()
cfg.themeMode.value = Theme.AUTO
cfg.themeColor.value = "#ff5d74a2"
qconfig.load(DEFAULT_CONFIG_PATH, cfg)
