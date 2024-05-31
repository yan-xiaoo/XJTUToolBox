from enum import Enum

from qfluentwidgets import StyleSheetBase, Theme
from .config import cfg


class StyleSheet(StyleSheetBase, Enum):
    """ Style sheet  """
    HOME_INTERFACE = "home_interface"
    SETTING_INTERFACE = "setting_interface"
    LOGIN_INTERFACE = "login_interface"
    LINK_CARD = "link_card"
    ACCOUNT_INTERFACE = "account_interface"
    ATTENDANCE_INTERFACE = "attendance_interface"
    AUTO_JUDGE_INTERFACE = "auto_judge_interface"
    TOOLBOX_INTERFACE = "toolbox_interface"
    TOOL_CARD = "tool_card"

    def path(self, theme=Theme.AUTO):
        theme = cfg.theme if theme == Theme.AUTO else theme
        return f"assets/qss/{theme.value.lower()}/{self.value}.qss"
