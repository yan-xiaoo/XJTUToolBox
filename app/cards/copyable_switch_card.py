from typing import Union

from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot, QTime, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QPushButton
from qfluentwidgets import SettingCard, FluentIconBase, ToolButton, FluentIcon


class CopyablePushSettingCard(SettingCard):
    """ Setting card with a push button """

    clicked = pyqtSignal()
    copied = pyqtSignal()

    def __init__(self, text, icon: Union[str, QIcon, FluentIconBase], title, content=None, parent=None):
        """
        Parameters
        ----------
        text: str
            the text of push button

        icon: str | QIcon | FluentIconBase
            the icon to be drawn

        title: str
            the title of card

        content: str
            the content of card

        parent: QWidget
            parent widget
        """
        super().__init__(icon, title, content, parent)
        self.button = QPushButton(text, self)
        self.copyButton = ToolButton(FluentIcon.COPY, self)
        self.hBoxLayout.addWidget(self.copyButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(5)
        self.hBoxLayout.addWidget(self.button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.copyButton.clicked.connect(lambda: self.copied.emit())
        self.button.clicked.connect(self.clicked)

        self.copied.connect(self._onCopied)

    @pyqtSlot()
    def _onCopied(self):
        self.copyButton.setIcon(FluentIcon.ACCEPT)
        QTimer.singleShot(2000, lambda: self.copyButton.setIcon(FluentIcon.COPY))
