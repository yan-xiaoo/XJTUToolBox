from qfluentwidgets import QConfig, qconfig, OptionsConfigItem, OptionsValidator, ConfigSerializer, Theme, \
    EnumSerializer
from enum import Enum


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


cfg = Config()
cfg.themeMode.value = Theme.AUTO
cfg.themeColor.value = "#ff5d74a2"
qconfig.load("config/config.json", cfg)
