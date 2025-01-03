from enum import Enum
from qfluentwidgets import FluentIconBase, Theme, getIconColor


class MyFluentIcon(FluentIconBase, Enum):
    ATTENDANCE = "attendance"
    SCHEDULE = "schedule"

    def path(self, theme=Theme.AUTO) -> str:
        return f"assets/icons/{self.value}_{getIconColor(theme)}.svg"
