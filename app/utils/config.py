import os

from packaging.version import parse
from qfluentwidgets import QConfig, qconfig, OptionsConfigItem, OptionsValidator, ConfigSerializer, Theme, \
    EnumSerializer
from enum import Enum
from .migrate_data import DATA_DIRECTORY


class BooleanSerializer(ConfigSerializer):
    def serialize(self, value):
        return value

    def deserialize(self, value):
        return bool(value)


class AttendanceLoginMethod(Enum):
    # 不设置，每次询问
    NONE = 0
    # 直接登录
    NORMAL = 1
    # WebVPN 登录
    WEBVPN = 2


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
