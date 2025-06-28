from typing import Union

from PyQt5.QtCore import pyqtSignal, Qt, pyqtSlot
from PyQt5.QtGui import QIcon
from qfluentwidgets import SettingCard, FluentIconBase, SwitchButton, IndicatorPosition, ConfigItem, qconfig, \
    IconWidget, Flyout, FlyoutAnimationType
from qfluentwidgets import FluentIcon as FIF


class CustomSwitchSettingCard(SettingCard):
    """ Setting card with switch button """

    checkedChanged = pyqtSignal(bool)

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title, content=None,
                 configItem: ConfigItem = None, parent=None):
        """
        Parameters
        ----------
        icon: str | QIcon | FluentIconBase
            the icon to be drawn

        title: str
            the title of card

        content: str
            the content of card

        configItem: ConfigItem
            configuration item operated by the card

        parent: QWidget
            parent widget
        """
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.switchButton = SwitchButton(
            self.tr('关'), self, IndicatorPosition.RIGHT)

        if configItem:
            self.setValue(qconfig.get(configItem))
            configItem.valueChanged.connect(self.setValue)

        # 可选的提示标签
        self.hintLabel = IconWidget(FIF.INFO, self)
        self.hintLabel.setFixedSize(20, 20)
        self.hintText = None
        self.hintLabel.setVisible(False)

        # add switch button to layout
        self.hBoxLayout.addWidget(self.hintLabel, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

        self.switchButton.checkedChanged.connect(self.__onCheckedChanged)
        self.hintLabel.mouseReleaseEvent = self.__onHintLabelClicked

    def __onHintLabelClicked(self, a0=None):
        Flyout.create(
            title="",
            content=self.hintText,
            target=self.hintLabel,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP
        )

    def __onCheckedChanged(self, isChecked: bool):
        """ switch button checked state changed slot """
        self.setValue(isChecked)
        self.checkedChanged.emit(isChecked)

    def showHint(self, text: str):
        """
        在开关旁边显示一个信息图标，点击后弹出提示显示一段内容，可以用于说明为何此开关没有启用
        :param text: 提示内容
        """
        self.hintLabel.setVisible(True)
        self.hintText = text

    def hideHint(self):
        """
        不再显示开关旁边的信息图表
        """
        self.hintLabel.setVisible(False)

    def setValue(self, isChecked: bool):
        if self.configItem:
            qconfig.set(self.configItem, isChecked)

        self.switchButton.setChecked(isChecked)
        self.switchButton.setText(
            self.tr('开') if isChecked else self.tr('关'))

    def setChecked(self, isChecked: bool):
        self.setValue(isChecked)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setSwitchEnabled(self, enabled: bool):
        """
        Enable or disable the switch button.

        :param enabled: True to enable, False to disable.
        """
        self.switchButton.setEnabled(enabled)
