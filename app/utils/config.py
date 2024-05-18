from qfluentwidgets import QConfig, qconfig, OptionsConfigItem, OptionsValidator, ConfigSerializer, Theme


class BooleanSerializer(ConfigSerializer):
    def serialize(self, value):
        return value

    def deserialize(self, value):
        return bool(value)


class Config(QConfig):
    hasReadLoginTip = OptionsConfigItem("one_time_notice", "read_login_tip", False,
                                        OptionsValidator([True, False]), BooleanSerializer())


cfg = Config()
cfg.themeMode.value = Theme.AUTO
cfg.themeColor.value = "#ff5d74a2"
qconfig.load("config/config.json", cfg)
