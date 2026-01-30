import datetime
from typing import Optional, Union

from PyQt5.QtCore import QTime, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import ExpandGroupSettingCard, BodyLabel, SwitchButton, IndicatorPosition, TimePicker, \
    FluentIconBase, PushButton, ConfigItem, MessageBox

from app.utils import cfg
from app.utils.config import TraySetting


class ScheduledNoticeCard(ExpandGroupSettingCard):
    """
    该卡片是一种设置卡片，可以用于创建“定时通知”类型的设置项目。
    所有的“定时通知”组件具有以下通用功能：
    1. 需要允许程序常驻托盘才能开启定时通知。因此，当用户尝试开启定时通知时，如果当前托盘设置不是“最小化到托盘”，则会弹出一个对话框，询问用户是否允许程序常驻托盘。
    2. 用户可以选择定时通知的时间。
    3. 用户可以立即测试推送通知的功能。
    该组件封装了一系列子组件，实现了这些通用功能的 ui 和逻辑。
    """
    # 信号：启用状态改变时触发，参数为当前启用状态（True 表示启用，False 表示禁用）。
    # 代码已经实现了在启用开关被点击时修改 enable_config_item 值的逻辑；在监听此信号时，无需再次修改。
    enable_changed = pyqtSignal(bool)
    # 信号：时间选择器的时间改变时触发，参数为当前选择的时间（datetime.time 对象）。
    # 代码已经实现了在时间改变时修改 time_config_item 值的逻辑；在监听此信号时，无需再次修改。
    time_changed = pyqtSignal(datetime.time)
    # 信号：测试按钮被点击时触发。
    # 代码中不包含对此信号的默认处理；你需要在监听此信号时实现测试推送通知的逻辑。
    test_button_clicked = pyqtSignal()

    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str, content: str, enable_config_item: ConfigItem,
                 time_config_item: ConfigItem, *,
                 time_setting_content: Optional[str]=None,
                 enable_test_button: bool=True,
                 dialog_parent: Optional[QWidget] = None, parent: Optional[QWidget] = None):
        """
        创建一张定时通知的设置卡片

        :param icon: 卡片图标
        :param title: 卡片标题
        :param content: 卡片展开前的内容描述
        :param enable_config_item: 与"是否启用“开关绑定的配置项
        :param time_config_item: 与时间选择器绑定的配置项
        :param time_setting_content: 时间选择器旁边的标签内容；如果省略，默认使用“查询时间”。
        :param initial_time: 时间选择器的初始时间；如果省略，默认使用配置项中的时间。
        :param dialog_parent: 此组件创建的模态对话框应当使用的父组件；如果省略，默认使用整个窗口。
        :param parent: 父组件
        """
        super().__init__(icon=icon, title=title, content=content, parent=parent)

        self.dialogParent = dialog_parent
        self.enableLabel = BodyLabel(title, self)
        self.enableButton = SwitchButton(self.tr("关"), self, IndicatorPosition.RIGHT)
        self.enableButton.setOnText(self.tr("开"))

        self.timeLabel = BodyLabel(time_setting_content or self.tr("查询时间"), self)
        self.timePicker = TimePicker(parent=self)
        self.timePicker.setTime(QTime(time_config_item.value.hour, time_config_item.value.minute))

        self.testLabel = BodyLabel(self.tr("立刻尝试推送通知"), self)
        self.testButton = PushButton(self.tr("立刻推送"), self)

        self.time_config_item = time_config_item
        self.enable_config_item = enable_config_item

        if not enable_config_item.value:
            self.enableButton.setChecked(False)
            self.timePicker.setEnabled(False)
            self.testButton.setEnabled(False)
        else:
            self.enableButton.setChecked(True)
            self.timePicker.setEnabled(True)
            self.testButton.setEnabled(True)

        # 延迟链接
        self.enableButton.checkedChanged.connect(self.onEnableButtonClicked)
        self.testButton.clicked.connect(lambda: self.test_button_clicked.emit())
        self.timePicker.timeChanged.connect(self.onTimeChanged)

        self.add(self.enableLabel, self.enableButton)
        self.add(self.timeLabel, self.timePicker)

        if enable_test_button:
            self.add(self.testLabel, self.testButton)

    @pyqtSlot()
    def onEnableButtonClicked(self):
        """
        启用开关被点击时触发
        该方法会检查当前托盘设置，如果不是“最小化到托盘”，则会弹出一个对话框，询问用户是否允许程序常驻托盘
        """
        if self.enableButton.isChecked():
            if cfg.traySetting.value != TraySetting.MINIMIZE:
                box = MessageBox(self.tr("开启定期查询"), self.tr("程序需要在后台运行以实现定时查询。\n是否允许程序常驻托盘？"),
                                 parent=self.dialogParent)
                box.yesButton.setText(self.tr("确定"))
                box.cancelButton.setText(self.tr("取消"))
                if box.exec():
                    cfg.traySetting.value = TraySetting.MINIMIZE
                    self.timePicker.setEnabled(True)
                    self.enable_config_item.value = True
                    self.testButton.setEnabled(True)
                else:
                    self.enableButton.setChecked(False)
                    self.timePicker.setEnabled(False)
                    cfg.noticeAutoSearch.value = False
                    self.testButton.setEnabled(False)
            else:
                self.timePicker.setEnabled(True)
                self.enable_config_item.value = True
                self.testButton.setEnabled(True)
            # 发送启用信号
            self.enable_changed.emit(True)
        else:
            self.timePicker.setEnabled(False)
            self.enable_config_item.value = False
            self.testButton.setEnabled(False)
            # 发送禁用信号
            self.enable_changed.emit(False)

    @pyqtSlot(QTime)
    def onTimeChanged(self, time: QTime):
        """时间选择器的时间改变时触发"""
        self.time_config_item.value = datetime.time(hour=time.hour(), minute=time.minute())
        # 发送时间改变信号
        self.time_changed.emit(self.time_config_item.value)

    def add(self, label, widget):
        """
        添加一个新的设置组件行

        :param label: 组件左侧的标签
        :param widget: 组件右侧的任意控件
        """
        w = QWidget()

        layout = QHBoxLayout(w)

        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(widget)

        # 添加组件到设置卡
        self.addGroupWidget(w)
