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

    def path(self, theme=Theme.AUTO):
        theme = cfg.theme if theme == Theme.AUTO else theme
        return f"assets/qss/{theme.value.lower()}/{self.value}.qss"
