import datetime
import json
import os

from packaging.version import parse
from qfluentwidgets import QConfig, qconfig, OptionsConfigItem, OptionsValidator, ConfigSerializer, Theme, \
    EnumSerializer, ConfigValidator, ConfigItem
from enum import Enum

from auth.util import old_fp_visitor_id, generate_user_agent
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


class CardValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    def correct(self, value):
        if not self.validate(value):
            return []
        return value


class CardSerializer(ConfigSerializer):
    def serialize(self, value):
        if isinstance(value, list):
            return json.dumps(value)
        return ""

    def deserialize(self, value):
        if isinstance(value, str):
            return json.loads(value)
        return []


class VisitorIdValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, str) and (len(value) == 32 or len(value) == 16) and all(c in "0123456789abcdef" for c in value)

    def correct(self, value):
        if not self.validate(value):
            return old_fp_visitor_id()
        return value


class VisitorIdSerializer(ConfigSerializer):
    def serialize(self, value):
        return value

    def deserialize(self, value):
        if isinstance(value, str):
            return value
        return old_fp_visitor_id()


class UserAgentValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, str)

    def correct(self, value):
        if not self.validate(value):
            return generate_user_agent()
        return value


class UserAgentSerializer(ConfigSerializer):
    def serialize(self, value):
        return value

    def deserialize(self, value):
        if isinstance(value, str):
            return value
        return generate_user_agent()


class StringValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, str)

    def correct(self, value):
        if value is None:
            return ""
        return str(value)


class StringSerializer(ConfigSerializer):
    def serialize(self, value):
        if value is None:
            return ""
        return str(value)

    def deserialize(self, value):
        if value is None:
            return ""
        return str(value)


class IntValidator(ConfigValidator):
    def __init__(self, default: int = 0, minimum: int | None = None, maximum: int | None = None):
        super().__init__()
        self.default = default
        self.minimum = minimum
        self.maximum = maximum

    def validate(self, value):
        if not isinstance(value, int):
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True

    def correct(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return self.default

        if self.minimum is not None:
            value = max(self.minimum, value)
        if self.maximum is not None:
            value = min(self.maximum, value)
        return value


class IntSerializer(ConfigSerializer):
    def serialize(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def deserialize(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class StrListValidator(ConfigValidator):
    def validate(self, value):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)

    def correct(self, value):
        if isinstance(value, list):
            return [str(v) for v in value]
        return []


class StrListSerializer(ConfigSerializer):
    """Serialize list[str] as JSON string for compatibility with existing config style."""

    def serialize(self, value):
        if isinstance(value, list):
            return json.dumps([str(v) for v in value], ensure_ascii=False)
        return "[]"

    def deserialize(self, value):
        if isinstance(value, list):
            # 兼容：若 qconfig 直接给出 list
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except json.JSONDecodeError:
                return []
        return []


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
    hasReadCloudflareTip = OptionsConfigItem("one_time_notice", "read_cloudflare_tip", False,
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
    # 是否通过请求成绩单，尝试绕过评教限制，查询学期成绩
    useScoreReport = OptionsConfigItem("Settings", "use_score_report",
                                       False, OptionsValidator([True, False]), BooleanSerializer())
    autoRetryAttendance = OptionsConfigItem("Settings", "auto_retry_attendance",
                                            True, OptionsValidator([True, False]), BooleanSerializer())
    traySetting = OptionsConfigItem("Settings", "tray_setting",
                                    TraySetting.UNKNOWN,
                                    OptionsValidator([TraySetting.UNKNOWN, TraySetting.QUIT, TraySetting.MINIMIZE]),
                                    EnumSerializer(TraySetting))
    noticeAutoSearch = OptionsConfigItem("Settings", "notice_auto_search",
                          False, OptionsValidator([True, False]), BooleanSerializer())
    noticeSearchTime = OptionsConfigItem("Settings", "notice_search_time",
                                         datetime.time(hour=18, minute=0), TimeValidator(), TimeSerializer())
    # 是否自动查询成绩
    scoreAutoSearch = OptionsConfigItem("Settings", "score_auto_search",
                                        False, OptionsValidator([True, False]), BooleanSerializer())
    # 每天自动查询成绩的时间
    scoreSearchTime = OptionsConfigItem("Settings", "score_search_time",
                                        datetime.time(hour=8, minute=0), TimeValidator(), TimeSerializer())
    # 上次查询成绩的日期
    lastScoreSearchTime = OptionsConfigItem("Settings", "last_score_search_time",
                                            datetime.datetime(1970, 1, 1), DateTimeValidator(),
                                            DateTimeSerializer())

    # 成绩定时查询：自定义命令 Hook
    scoreHookEnable = OptionsConfigItem(
        "Settings", "score_hook_enable",
        False, OptionsValidator([True, False]), BooleanSerializer()
    )
    scoreHookProgram = ConfigItem(
        "Settings", "score_hook_program",
        "", StringValidator(), StringSerializer()
    )
    # argv 参数列表（存储为 list[str]）
    scoreHookArgs = ConfigItem(
        "Settings", "score_hook_args",
        ["--payload", "${payload}"], StrListValidator(), StrListSerializer()
    )
    # 子程序最长执行时间
    scoreHookTimeoutSec = ConfigItem(
        "Settings", "score_hook_timeout_sec",
        15, IntValidator(default=15, minimum=1, maximum=600), IntSerializer()
    )
    # 两次允许执行的最短间隔时间
    scoreHookCooldownNewSec = ConfigItem(
        "Settings", "score_hook_cooldown_new_sec",
        300, IntValidator(default=300, minimum=0, maximum=86400), IntSerializer()
    )
    # 在点击“立刻推送”（强制执行）时，允许的最短间隔时间，防止误触
    scoreHookCooldownForceSec = ConfigItem(
        "Settings", "score_hook_cooldown_force_sec",
        3, IntValidator(default=3, minimum=0, maximum=3600), IntSerializer()
    )
    # 是否在 payload 中包含完整成绩信息（否则只包含变动的成绩）
    scoreHookIncludeFullScores = OptionsConfigItem(
        "Settings", "score_hook_include_full_scores",
        False, OptionsValidator([True, False]), BooleanSerializer()
    )
    # 是否保留 payload 文件，便于调试
    scoreHookKeepPayloadFiles = OptionsConfigItem(
        "Settings", "score_hook_keep_payload_files",
        False, OptionsValidator([True, False]), BooleanSerializer()
    )

    autoStart = OptionsConfigItem("Settings", "auto_start",
                                  False, OptionsValidator([True, False]), BooleanSerializer())
    # 这其实不是个设置项目，只是用来存储上次搜索的时间
    lastSearchTime = OptionsConfigItem("Settings", "last_search_time",
                                         datetime.datetime(1970, 1, 1), DateTimeValidator(),
                                         DateTimeSerializer())
    showAvatarOnSideBar = OptionsConfigItem("Settings", "show_avatar_on_sidebar",
                                    True, OptionsValidator([True, False]), BooleanSerializer())
    cardLayout = ConfigItem("Settings", "card_layout", [], CardValidator(), CardSerializer())
    useKeyring = OptionsConfigItem("Settings", "use_keyring", True, OptionsValidator([True, False]),
                                   BooleanSerializer())
    # 同样不是设置项目；这个项目存储登录时使用的 fp_visitor_id，以保证每次启动程序后登录时使用相同的 ID
    loginId = ConfigItem("Settings", "login_id", old_fp_visitor_id(), VisitorIdValidator(), VisitorIdSerializer())
    # 同样不是设置项目；这个项目存储登录时使用的 User-Agent，以保证每次启动程序后登录时使用相同的 UA
    userAgent = ConfigItem("Settings", "user_agent", generate_user_agent(), UserAgentValidator(), UserAgentSerializer())

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
