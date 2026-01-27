import datetime
import json

from PyQt5.QtCore import pyqtSlot, QDate, Qt, QStandardPaths, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QTableWidgetItem, \
    QFileDialog
from PyQt5.QtGui import QFont, QPixmap
from qfluentwidgets import ScrollArea, TitleLabel, StrongBodyLabel, ComboBox, CalendarPicker, PrimaryPushButton, \
    TableWidget, InfoBar, InfoBarPosition, PushButton, FluentStyleSheet, Theme, isDarkTheme, MessageBox

from ..components.MultiSelectionComboBox import MultiSelectionComboBox
from ..threads.CFEmptyRoomThread import CFEmptyRoomThread
from ..threads.EmptyRoomThread import EmptyRoomThread
from ..threads.ProcessWidget import ProcessWidget
from ..utils import StyleSheet, DataManager, cfg, accounts
from ehall.empty_room import CAMPUS_BUILDING_DICT


class CellWidget(QWidget):
    """
    教室状态单元格组件
    """
    def __init__(self, is_occupied=False, parent=None):
        super().__init__(parent)
        self.is_occupied = is_occupied
        self.text_label = None
        self.setupUI()

    def setupUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # 创建状态文本
        self.text_label = QLabel()
        self.text_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self.text_label.setFont(font)

        if self.is_occupied:
            # 占用状态 - 红色主题
            self.text_label.setText(self.tr("占用"))
        else:
            # 空闲状态 - 绿色主题
            self.text_label.setText(self.tr("空闲"))

        self._onThemeChanged()
        layout.addWidget(self.text_label, 1)

        cfg.themeChanged.connect(self._onThemeChanged)

        # 设置整体样式
        self.setStyleSheet("""
            CellWidget {
                background-color: transparent;
                border-radius: 6px;
            }
            CellWidget:hover {
                background-color: rgba(0, 0, 0, 0.03);
            }
        """)

    def darkTheme(self):
        if self.is_occupied:
            # 占用状态 - 红色主题
            self.text_label.setStyleSheet("""
                QLabel {
                    color: #f46175;
                    background-color: #191717;
                    border: 1px solid #724e51;
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)
        else:
            # 空闲状态 - 绿色主题
            self.text_label.setStyleSheet("""
                QLabel {
                    color: #45e84b;
                    background-color: #171917;
                    border: 1px solid #38633a;
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)

    def lightTheme(self):
        if self.is_occupied:
            # 占用状态 - 红色主题
            self.text_label.setStyleSheet("""
                QLabel {
                    color: #d32f2f;
                    background-color: #ffebee;
                    border: 1px solid #ffcdd2;
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)
        else:
            # 空闲状态 - 绿色主题
            self.text_label.setStyleSheet("""
                QLabel {
                    color: #388e3c;
                    background-color: #e8f5e8;
                    border: 1px solid #c8e6c9;
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)

    @pyqtSlot()
    def _onThemeChanged(self):
        self.darkTheme() if isDarkTheme() else self.lightTheme()


class EmptyRoomInterface(ScrollArea):
    """
    空闲教室查询界面
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self._onlyNotice = None
        self.setObjectName("EmptyRoomInterface")

        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.vBoxLayout = QVBoxLayout(self.view)

        self.titleLabel = TitleLabel(self.tr("空闲教室"), self.view)
        self.titleLabel.setContentsMargins(10, 15, 0, 0)
        self.titleLabel.setObjectName("titleLabel")
        self.vBoxLayout.addWidget(self.titleLabel)

        # self.minorLabel = StrongBodyLabel(self.tr("查询当前空闲的教室"), self.view)
        # self.minorLabel.setContentsMargins(15, 5, 0, 0)
        # self.vBoxLayout.addWidget(self.minorLabel)
        # self.vBoxLayout.addSpacing(10)

        self.viewFrame = QFrame(self.view)
        self.viewLayout = QVBoxLayout(self.viewFrame)
        self.viewLayout.setSpacing(20)
        self.vBoxLayout.addWidget(self.viewFrame, stretch=1)

        self.methodComboBox = ComboBox(parent=self.view)
        self.methodComboBox.addItems([self.tr("直接查询"), self.tr("Cloudflare CDN 查询")])
        self.viewLayout.addWidget(self.methodComboBox)

        self.commandFrame = QFrame(self.view)
        self.commandLayout = QHBoxLayout(self.commandFrame)

        self.campusBox = ComboBox(parent=self.view)
        items = ["兴庆校区", "雁塔校区", "创新港校区", "曲江校区", "苏州校区"]
        self.campusBox.addItems(items)

        self.buildingBox = MultiSelectionComboBox(all_select_option=False, parent=self.view)
        self.buildingBox.setPlaceholderText(self.tr("选择教学楼"))

        self.calendar = CalendarPicker()
        self.calendar.setDate(QDate.currentDate())

        self.cfCalendarComboBox = ComboBox(parent=self.view)
        # CF 查询只支持两天
        self.cfCalendarComboBox.addItems([self.tr("今天"), self.tr("明天")])
        self.cfCalendarComboBox.setCurrentIndex(0)
        self.cfCalendarComboBox.setVisible(False)

        self.searchButton = PrimaryPushButton(self.tr("查询"), self.view)
        self.searchButton.setMinimumWidth(150)
        self.searchButton.clicked.connect(self._onSearchButtonClicked)

        self.cfSearchButton = PrimaryPushButton(self.tr("查询"), self.view)
        self.cfSearchButton.setMinimumWidth(150)
        self.cfSearchButton.setVisible(False)

        self.exportButton = PushButton(self.tr("导出图片..."), self.view)
        self.exportButton.clicked.connect(self._onExportButtonClicked)

        self.emptyRoomTable = TableWidget(self.view)
        # 随便先设置一个行数，后面会根据查询结果调整
        self.emptyRoomTable.setRowCount(7)
        self.emptyRoomTable.setColumnCount(14)
        self.emptyRoomTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)

        self.emptyRoomTable.setHorizontalHeaderLabels(
            [self.tr("座位"), "1", "2", "3", "4", self.tr("午休"), "5", "6", "7", "8", self.tr("晚休"), "9", "10", "11"])
        self.emptyRoomTable.verticalHeader().setVisible(False)
        self.emptyRoomTable.setEditTriggers(TableWidget.NoEditTriggers)
        self.emptyRoomTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)

        self.commandLayout.addWidget(self.campusBox, stretch=1)
        self.commandLayout.addWidget(self.buildingBox, stretch=2)
        self.commandLayout.addWidget(self.calendar, stretch=1)
        self.commandLayout.addWidget(self.cfCalendarComboBox, stretch=1)
        self.commandLayout.addWidget(self.searchButton, stretch=1)
        self.commandLayout.addWidget(self.cfSearchButton, stretch=1)
        self.commandLayout.addWidget(self.exportButton, stretch=1)

        self.thread_ = EmptyRoomThread()
        self.thread_.finished.connect(self.unlock)
        self.thread_.result.connect(self._onReceiveResultAndSave)
        self.thread_.error.connect(self.onThreadError)
        self.thread_.success.connect(self.onThreadSuccess)

        self.cfThread = CFEmptyRoomThread()
        self.cfThread.finished.connect(self.unlock)
        self.cfThread.result.connect(self._onReceiveResultAndSave)
        self.cfThread.error.connect(self.onThreadError)
        self.cfThread.success.connect(self.onThreadSuccess)

        self.processWidget = ProcessWidget(self.thread_, parent=self.view, stoppable=True)
        self.processWidget.setVisible(False)

        self.cfProcessWidget = ProcessWidget(self.cfThread, parent=self.view, stoppable=True)
        self.cfProcessWidget.setVisible(False)

        # 延迟加载教室数据的相关变量
        self._pendingRoomData = {}  # 待处理的教室数据
        self._loadRoomIndex = 0  # 当前加载的教室索引
        self._roomBatchSize = 10  # 每批加载的教室数量
        self._loadRoomTimer = QTimer(self)  # 延迟加载定时器
        self._roomLabels = []  # 教室标签列表

        self.viewLayout.addWidget(self.commandFrame)
        self.viewLayout.addWidget(self.processWidget)
        self.viewLayout.addWidget(self.cfProcessWidget)
        self.viewLayout.addWidget(self.emptyRoomTable, stretch=1)

        # 先更新一次教学楼下拉框的内容
        self._updateBuildingBox(save_setting=False)

        self.loadQuerySetting()
        self.loadQueryResult()
        self.campusBox.currentIndexChanged.connect(self._updateBuildingBox)
        self.buildingBox.selectChanged.connect(self.saveQuerySetting)
        self.methodComboBox.currentIndexChanged.connect(self._onMethodComboBoxChanged)
        self.cfSearchButton.clicked.connect(self._onCFSearchButtonClicked)

        cfg.themeChanged.connect(self._onThemeChanged)
        accounts.currentAccountChanged.connect(self._onCurrentAccountChanged)

        self._onCurrentAccountChanged()

        StyleSheet.EMPTY_ROOM_INTERFACE.apply(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

    @pyqtSlot()
    def _updateBuildingBox(self, save_setting=True):
        """
        更新教学楼下拉框的内容
        """
        selected_campus = self.campusBox.currentText()
        if not selected_campus:
            self.buildingBox.clear()
            return

        buildings = CAMPUS_BUILDING_DICT.get(selected_campus, [])

        self.buildingBox.clear()
        self.buildingBox.addItems(buildings)

        if save_setting:
            self.saveQuerySetting()

    @pyqtSlot()
    def _onCurrentAccountChanged(self):
        if accounts.current is not None:
            if accounts.current.type == accounts.current.POSTGRADUATE:
                self.methodComboBox.setCurrentIndex(1)
                self.methodComboBox.setEnabled(False)
                self.selectQueryType(use_cloudflare=True)
            else:
                self.methodComboBox.setEnabled(True)
                self.selectQueryType(use_cloudflare=self.methodComboBox.currentIndex() == 1)

    @pyqtSlot()
    def _onMethodComboBoxChanged(self):
        self.selectQueryType(use_cloudflare=self.methodComboBox.currentIndex() == 1)

    def selectQueryType(self, use_cloudflare=False):
        """
        设置当前使用直接查询还是 Cloudflare CDN 查询方式。设置后，部分页面控件将会变更。
        """
        if use_cloudflare:
            self.cfCalendarComboBox.setVisible(True)
            self.cfSearchButton.setVisible(True)
            self.calendar.setVisible(False)
            self.searchButton.setVisible(False)
        else:
            self.cfCalendarComboBox.setVisible(False)
            self.cfSearchButton.setVisible(False)
            self.calendar.setVisible(True)
            self.searchButton.setVisible(True)

    @pyqtSlot()
    def _onSearchButtonClicked(self):
        if accounts.current is not None and accounts.current.type == accounts.current.POSTGRADUATE:
            self.error("", self.tr("研究生账号请使用 Cloudflare CDN 方式查询"), duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)
            return

        if not self.campusBox.currentText() or not self.buildingBox.selectedItems():
            self.error("", self.tr("请选择校区和教学楼。"), duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)
            return

        self.lock()
        self.thread_.campus_name = self.campusBox.currentText()
        self.thread_.building_names = [one.text for one in self.buildingBox.selectedItems()]
        self.thread_.date = self.calendar.getDate().toPyDate().isoformat()
        self.processWidget.setVisible(True)
        self.thread_.start()

    @pyqtSlot()
    def _onCFSearchButtonClicked(self):
        if not cfg.hasReadCloudflareTip.value:
            if not self.showCFTip():
                return

        if not self.campusBox.currentText() or not self.buildingBox.selectedItems():
            self.error("", self.tr("请选择校区和教学楼。"), duration=3000, position=InfoBarPosition.TOP_RIGHT,
                       parent=self)
            return

        self.lock()
        self.cfThread.campus_name = self.campusBox.currentText()
        self.cfThread.building_names = [one.text for one in self.buildingBox.selectedItems()]
        index = self.cfCalendarComboBox.currentIndex()
        if index == 1:
            self.cfThread.date = datetime.date.today() + datetime.timedelta(days=1)
        else:
            self.cfThread.date = datetime.date.today()
        self.cfProcessWidget.setVisible(True)
        self.cfThread.start()

    def showCFTip(self) -> bool:
        """显示第一次使用 Cloudflare CDN 时的说明"""
        w = MessageBox(self.tr("Cloudflare CDN 使用说明"), self.tr("程序将从 Cloudflare CDN 获取空闲教室信息，这种方式不需要登录校园网，但数据可能不是最新的。\n"
                                                               "获取数据时，程序不会发送任何与账户相关的隐私信息。\n"
                                                               "此功能并不保证稳定，如果出现错误，请改用直接查询方式。"),
                       self)
        w.yesButton.setText(self.tr("继续"))
        w.cancelButton.setText(self.tr("取消"))
        if w.exec():
            cfg.hasReadCloudflareTip.value = True
            return True
        else:
            return False

    @pyqtSlot()
    def _onExportButtonClicked(self):
        """
        导出表格为图片
        """
        path, ok = QFileDialog.getSaveFileName(
            parent=self,
            caption=self.tr('保存空闲教室为图片'),
            directory=QStandardPaths.writableLocation(QStandardPaths.DesktopLocation),
            filter='PNG (*.png)'
        )
        if not ok or not path:
            return
        self.exportTableToImage(path)
        self.success(self.tr("导出成功"), self.tr("空闲教室已成功导出为图片。"), duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    @pyqtSlot(dict)
    def _onReceiveResultAndSave(self, result: dict):
        self.saveQueryResult(result)
        self._onReceiveResult(result)

    @pyqtSlot(dict)
    def _onReceiveResult(self, empty_room_info: dict):
        # 停止之前可能正在进行的加载
        self._loadRoomTimer.stop()

        # 清空表格内容
        self.emptyRoomTable.clearContents()
        self.emptyRoomTable.setRowCount(len(empty_room_info))
        self.emptyRoomTable.verticalHeader().setVisible(True)
        self.emptyRoomTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)

        # 准备延迟加载的数据
        self._pendingRoomData = empty_room_info
        self._roomLabels = list(empty_room_info.keys())
        self._loadRoomIndex = 0

        # 设置表格行标签
        self.emptyRoomTable.setVerticalHeaderLabels(self._roomLabels)

        # 调整行高以适应新的组件
        self.emptyRoomTable.verticalHeader().setDefaultSectionSize(40)

        # 如果有数据，启动延迟加载
        if empty_room_info:
            QTimer.singleShot(50, self._startLoadingRooms)  # 50ms后开始加载

    def _startLoadingRooms(self):
        """
        开始加载教室数据
        """
        if self._loadRoomIndex >= len(self._roomLabels):
            return

        # 计算当前批次的教室数据
        batch_data = {}
        for i in range(self._roomBatchSize):
            index = self._loadRoomIndex + i
            if index >= len(self._roomLabels):
                break
            room = self._roomLabels[index]
            batch_data[room] = self._pendingRoomData[room]

        # 更新表格内容
        self._updateTableWithRoomData(batch_data)

        # 更新索引
        self._loadRoomIndex += len(batch_data)

        # 继续加载下一批
        if self._loadRoomIndex < len(self._roomLabels):
            QTimer.singleShot(50, self._startLoadingRooms)  # 50ms后加载下一批

    def _updateTableWithRoomData(self, room_data: dict):
        """
        用教室数据更新表格
        """
        for room, value in room_data.items():
            row = self._roomLabels.index(room)
            status = value["status"]
            self.emptyRoomTable.setItem(row, 0, QTableWidgetItem(str(value["size"])))
            for period in range(11):
                # 创建自定义的CellWidget来替代纯文字
                is_occupied = status[period] == 1
                cell_widget = CellWidget(is_occupied=is_occupied)
                self.emptyRoomTable.setCellWidget(row, self._getSuitablePeriod(period), cell_widget)

    @pyqtSlot()
    def _onThemeChanged(self):
        # 因为在导出图片时手动修改了字的颜色，字的颜色就无法跟随主题自动切换了
        # 所以需要在主题切换时重新设置字的颜色
        for row in range(self.emptyRoomTable.rowCount()):
            item = self.emptyRoomTable.item(row, 0)
            if item is not None:
                item.setForeground(Qt.GlobalColor.white if isDarkTheme() else Qt.GlobalColor.black)

    @staticmethod
    def _getSuitablePeriod(period):
        if 0 <= period <= 3:
            return period + 1
        elif 4 <= period <= 7:
            return period + 2
        else:
            return period + 3

    def lock(self):
        self.searchButton.setEnabled(False)

    def unlock(self):
        self.searchButton.setEnabled(True)

    @pyqtSlot(str, str)
    def onThreadError(self, title, msg):
        self.error(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    @pyqtSlot(str, str)
    def onThreadSuccess(self, title, msg):
        self.success(title, msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self)

    def success(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个成功的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.success(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.success(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT,
                                               parent=parent, isClosable=True)

    def error(self, title, msg, duration=2000, position=InfoBarPosition.TOP_RIGHT, parent=None):
        """
        显示一个错误的通知。如果已经存在通知，已存在的通知会被立刻关闭。
        :param duration: 通知显示时间
        :param position: 通知显示位置
        :param parent: 通知的父窗口
        :param title: 通知标题
        :param msg: 通知内容
        """
        if self._onlyNotice is not None:
            try:
                self._onlyNotice.close()
            except RuntimeError:
                # RuntimeError: wrapped C/C++ object of type InfoBar has been deleted
                # 这个异常无所谓，忽略
                self._onlyNotice = None
        if self.window().isActiveWindow():
            self._onlyNotice = InfoBar.error(title, msg, duration=duration, position=position, parent=parent)
        else:
            self._onlyNotice = InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=parent,
                                             isClosable=True)

    def saveQuerySetting(self):
        """
        保存查询设置
        """
        manager = DataManager()
        manager.write_json("empty_room_query.json", {
            "campus": self.campusBox.currentText(),
            "buildings": [one.text for one in self.buildingBox.selectedItems()]
        }, allow_overwrite=True)

    def loadQuerySetting(self):
        """
        加载查询设置
        """
        manager = DataManager()
        try:
            data = manager.read_json("empty_room_query.json")
        except (OSError, json.JSONDecodeError, KeyError):
            return

        campus = data.get("campus", "")
        buildings = data.get("buildings", [])

        if campus:
            index = self.campusBox.findText(campus)
            if index != -1:
                self.campusBox.setCurrentIndex(index)

        self.buildingBox.clear()
        self.buildingBox.addItems(CAMPUS_BUILDING_DICT.get(campus, []))

        for building in buildings:
            index = self.buildingBox.findText(building)
            if index != -1:
                self.buildingBox.addSelectIndex(index)

    def exportTableToImage(self, image_path: str):
        """
        导出表格为图片
        :param image_path: 图片保存路径
        """
        original_size = self.emptyRoomTable.size()

        # 计算完整内容的总尺寸
        total_width = self.emptyRoomTable.verticalHeader().width()
        total_height = self.emptyRoomTable.horizontalHeader().height()

        for row in range(self.emptyRoomTable.rowCount()):
            total_height += self.emptyRoomTable.rowHeight(row)
        for col in range(self.emptyRoomTable.columnCount()):
            total_width += self.emptyRoomTable.columnWidth(col)

        # 设置新尺寸以容纳全部内容
        self.emptyRoomTable.resize(total_width, total_height)

        # 创建图像并渲染
        image = QPixmap(self.emptyRoomTable.size())
        image.fill(Qt.white)
        # 临时修改主题，防止白色背景下看不见字
        FluentStyleSheet.TABLE_VIEW.apply(self.emptyRoomTable, theme=Theme.LIGHT)
        for row in range(self.emptyRoomTable.rowCount()):
            item = self.emptyRoomTable.item(row, 0)
            if item is not None:
                item.setForeground(Qt.GlobalColor.black)
            for col in range(self.emptyRoomTable.columnCount()):
                item = self.emptyRoomTable.cellWidget(row, col)
                if item is not None:
                    item.lightTheme()

        self.emptyRoomTable.render(image)

        # 恢复原始尺寸和主题
        self.emptyRoomTable.resize(original_size)
        FluentStyleSheet.TABLE_VIEW.apply(self.emptyRoomTable, theme=Theme.AUTO)
        for row in range(self.emptyRoomTable.rowCount()):
            item = self.emptyRoomTable.item(row, 0)
            if item is not None:
                item.setForeground(Qt.GlobalColor.white if isDarkTheme() else Qt.GlobalColor.black)
            for col in range(self.emptyRoomTable.columnCount()):
                item = self.emptyRoomTable.cellWidget(row, col)
                if item is not None:
                    item._onThemeChanged()

        # 保存图像
        image.save(image_path)

    @staticmethod
    def saveQueryResult(result: dict):
        """
        保存查询结果到文件
        :param result: 查询结果字典
        """
        manager = DataManager()
        manager.write_json("empty_room_result.json", result, allow_overwrite=True)

    def loadQueryResult(self):
        """
        加载查询结果
        """
        manager = DataManager()
        try:
            result = manager.read_json("empty_room_result.json")
        except (OSError, json.JSONDecodeError):
            return

        self._onReceiveResult(result)
