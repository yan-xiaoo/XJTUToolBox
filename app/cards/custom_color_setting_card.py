# coding:utf-8
from typing import Union
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtWidgets import QWidget, QLabel, QButtonGroup, QVBoxLayout, QPushButton, QHBoxLayout

from qfluentwidgets import ColorDialog, ExpandGroupSettingCard, RadioButton, qconfig, ColorConfigItem, FluentIconBase, \
    Theme, isDarkTheme


class CustomColorSettingCard(ExpandGroupSettingCard):
    """ Custom color setting card """

    colorChanged = pyqtSignal(QColor)

    def __init__(self, configItem: ColorConfigItem, icon: Union[str, QIcon, FluentIconBase], title: str,
                 content=None, parent=None, enableAlpha=False, default_color=None):
        """
        Parameters
        ----------
        configItem: ColorConfigItem
            options config item

        icon: str | QIcon | FluentIconBase
            the icon to be drawn

        title: str
            the title of setting card

        content: str
            the content of setting card

        parent: QWidget
            parent window

        enableAlpha: bool
            whether to enable the alpha channel
        """
        super().__init__(icon, title, content, parent=parent)
        self.enableAlpha = enableAlpha
        self.configItem = configItem
        self.defaultColor = default_color or QColor(configItem.defaultValue)
        self.customColor = QColor(qconfig.get(configItem))

        self.choiceLabel = QLabel(self)

        qconfig.themeChanged.connect(self.onThemeChanged)

        self.radioWidget = QWidget(self.view)
        self.radioLayout = QVBoxLayout(self.radioWidget)
        self.defaultRadioButton = RadioButton(
            self.tr('默认颜色'), self.radioWidget)
        self.customRadioButton = RadioButton(
            self.tr('自定义颜色'), self.radioWidget)
        self.buttonGroup = QButtonGroup(self)

        self.customColorWidget = QWidget(self.view)
        self.customColorLayout = QHBoxLayout(self.customColorWidget)
        self.customLabel = QLabel(
            self.tr('自定义颜色'), self.customColorWidget)
        self.chooseColorButton = QPushButton(
            self.tr('选择颜色'), self.customColorWidget)

        self.__initWidget()

    @pyqtSlot(Theme)
    def onThemeChanged(self, _):
        self.choiceLabel.setStyleSheet("color: #ffffff;" if isDarkTheme() else "color: #000000;")

    def __initWidget(self):
        self.__initLayout()

        if self.defaultColor != self.customColor:
            self.customRadioButton.setChecked(True)
            self.chooseColorButton.setEnabled(True)
        else:
            self.defaultRadioButton.setChecked(True)
            self.chooseColorButton.setEnabled(False)

        self.choiceLabel.setText(self.buttonGroup.checkedButton().text())
        self.choiceLabel.adjustSize()
        self.onThemeChanged(qconfig.theme)

        self.chooseColorButton.setObjectName('chooseColorButton')

        self.buttonGroup.buttonClicked.connect(self.__onRadioButtonClicked)
        self.chooseColorButton.clicked.connect(self.__showColorDialog)

    def __initLayout(self):
        self.addWidget(self.choiceLabel)

        self.radioLayout.setSpacing(19)
        self.radioLayout.setAlignment(Qt.AlignTop)
        self.radioLayout.setContentsMargins(48, 18, 0, 18)
        self.buttonGroup.addButton(self.customRadioButton)
        self.buttonGroup.addButton(self.defaultRadioButton)
        self.radioLayout.addWidget(self.customRadioButton)
        self.radioLayout.addWidget(self.defaultRadioButton)
        self.radioLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        self.customColorLayout.setContentsMargins(48, 18, 44, 18)
        self.customColorLayout.addWidget(self.customLabel, 0, Qt.AlignLeft)
        self.customColorLayout.addWidget(self.chooseColorButton, 0, Qt.AlignRight)
        self.customColorLayout.setSizeConstraint(QHBoxLayout.SetMinimumSize)

        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.addGroupWidget(self.radioWidget)
        self.addGroupWidget(self.customColorWidget)

    def __onRadioButtonClicked(self, button: RadioButton):
        """ radio button clicked slot """
        if button.text() == self.choiceLabel.text():
            return

        self.choiceLabel.setText(button.text())
        self.choiceLabel.adjustSize()

        if button is self.defaultRadioButton:
            self.chooseColorButton.setDisabled(True)
            qconfig.set(self.configItem, self.defaultColor)
            if self.defaultColor != self.customColor:
                self.colorChanged.emit(self.defaultColor)
        else:
            self.chooseColorButton.setDisabled(False)
            qconfig.set(self.configItem, self.customColor)
            if self.defaultColor != self.customColor:
                self.colorChanged.emit(self.customColor)

    def __showColorDialog(self):
        """ show color dialog """
        w = ColorDialog(
            qconfig.get(self.configItem), self.tr('自定义颜色'), self.window(), self.enableAlpha)
        # 强行汉化一下颜色窗口
        w.yesButton.setText(self.tr('确定'))
        w.cancelButton.setText(self.tr('取消'))
        w.editLabel.setText(self.tr('编辑颜色'))
        w.redLabel.setText(self.tr('红'))
        w.greenLabel.setText(self.tr('绿'))
        w.blueLabel.setText(self.tr('蓝'))
        w.opacityLabel.setText(self.tr('透明度'))
        w.colorChanged.connect(self.__onCustomColorChanged)
        w.exec()

    def __onCustomColorChanged(self, color):
        """ custom color changed slot """
        qconfig.set(self.configItem, color)
        self.customColor = QColor(color)
        self.colorChanged.emit(color)
