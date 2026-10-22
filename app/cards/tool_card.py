from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeyEvent, QMouseEvent
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, FluentIcon, FluentIconBase, IconWidget, ToggleToolButton
from ..utils import StyleSheet


class ToolCard(CardWidget):
    """展示紧凑功能入口，并提供独立的侧栏固定操作。"""

    cardClicked = pyqtSignal()
    pinClicked = pyqtSignal()

    def __init__(self, icon: FluentIconBase, title: str, content: str,
                 parent: QWidget | None = None) -> None:
        """构造横向图标、说明及图钉布局。"""
        super().__init__(parent)
        # 卡片会跨组移动，不能使用缓存旧坐标的悬停位移动画。
        self.setBorderRadius(8)
        self.setClickEnabled(True)
        self.setFixedSize(240, 100)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(title)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 10, 12)
        layout.setSpacing(8)
        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(28, 28)
        layout.addWidget(self.iconWidget)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(4)
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setObjectName("titleLabel")
        self.titleLabel.setWordWrap(True)
        self.contentLabel = QLabel(content, self)
        self.contentLabel.setObjectName("contentLabel")
        self.contentLabel.setWordWrap(True)
        textLayout.addWidget(self.titleLabel)
        textLayout.addWidget(self.contentLabel)
        layout.addLayout(textLayout, 1)
        self.pinButton = ToggleToolButton(FluentIcon.PIN, self)
        self.pinButton.setFixedSize(32, 32)
        self.pinButton.setAccessibleName(f"固定{title}到侧栏")
        self.pinButton.clicked.connect(self.pinClicked)
        layout.addWidget(self.pinButton, 0, Qt.AlignTop)
        StyleSheet.TOOL_CARD.apply(self)

    def setPinned(self, pinned: bool) -> None:
        """更新固定状态，图钉点击不会打开页面。"""
        self.pinButton.setChecked(pinned)
        self.pinButton.setToolTip(self.tr("取消固定") if pinned else self.tr("固定到侧栏"))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """仅在卡片内释放左键时打开功能。"""
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.cardClicked.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """支持键盘打开功能。"""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.cardClicked.emit()
        else:
            super().keyPressEvent(event)
