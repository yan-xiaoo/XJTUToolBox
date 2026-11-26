from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from PyQt5.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QKeyEvent, QMouseEvent, QShowEvent
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, Flyout, FlyoutViewBase, FluentIcon, FluentIconBase, MSFluentWindow,
    NavigationBarPushButton, NavigationItemPosition, PushButton, ScrollArea,
    ToggleToolButton, themeColor,
)

from ..utils.config import cfg

if TYPE_CHECKING:
    from ..ToolBoxInterface import ToolBoxInterface


@dataclass(frozen=True)
class Feature:
    """描述各个入口共用的业务功能及其唯一页面。"""

    key: str
    title: str
    description: str
    category: str
    icon: FluentIconBase
    page: QWidget
    sidebarTitle: str | None = None


class DraggableNavigationButton(NavigationBarPushButton):
    """支持拖动排序且不会在拖动结束时误触跳转的导航按钮。"""

    dragMoved = pyqtSignal(str, QPoint)
    dragFinished = pyqtSignal(str, QPoint)
    dragCancelled = pyqtSignal()

    def __init__(self, feature: Feature, parent: QWidget) -> None:
        """初始化功能按钮及拖动状态。"""
        super().__init__(feature.icon, feature.sidebarTitle or feature.title, True, parent=parent)
        self.key = feature.key
        self._press: QPoint | None = None
        self._dragging = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(feature.title)
        self.setToolTip(f"{feature.title}（拖动调整顺序）")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """记录左键起点，用系统拖动阈值区分点击。"""
        if event.button() == Qt.LeftButton:
            self._press = event.globalPos()
            self._dragging = False
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """超过阈值后向导航控制器报告插入位置。"""
        if self._press is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self._press).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                self.dragMoved.emit(self.key, event.globalPos())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """提交拖动或正常点击；取消后释放鼠标不触发跳转。"""
        pressed = self._press is not None
        self._press = None
        self.isPressed = False
        self.update()
        if self._dragging:
            self._dragging = False
            self.dragFinished.emit(self.key, event.globalPos())
        elif pressed and event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """支持键盘打开功能和取消当前拖动。"""
        if event.key() == Qt.Key_Escape and self._press is not None:
            self.cancelDrag()
            self.dragCancelled.emit()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.click()
        else:
            super().keyPressEvent(event)

    def cancelDrag(self) -> None:
        """清除完整的鼠标操作状态，后续释放事件不再提交拖动或点击。"""
        self._press = None
        self._dragging = False
        self.isPressed = False
        self.update()


class FeatureRow(QWidget):
    """将打开功能与固定操作分成两个独立的点击区域。"""

    def __init__(self, feature: Feature, parent: QWidget) -> None:
        """创建一行带图钉的功能入口。"""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.openButton = PushButton(feature.icon, feature.title, self)
        self.openButton.setMinimumHeight(36)
        self.pinButton = ToggleToolButton(FluentIcon.PIN, self)
        self.pinButton.setAccessibleName(f"固定{feature.title}到侧栏")
        layout.addWidget(self.openButton, 1)
        layout.addWidget(self.pinButton)

    def setPinned(self, pinned: bool) -> None:
        """更新图钉显示，不触发页面导航。"""
        self.pinButton.setChecked(pinned)
        self.pinButton.setToolTip("取消固定" if pinned else "固定到侧栏")


class FeatureFlyout(Flyout):
    """不接管侧栏鼠标事件、不抢焦点的功能浮层。"""

    def __init__(self, view: FlyoutViewBase, parent: QWidget) -> None:
        """保留浮层外观，改用非模态工具窗口以允许点击更多按钮。"""
        super().__init__(view, parent, isDeleteOnClose=False)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    def showEvent(self, event: QShowEvent) -> None:
        """跳过 Flyout 主动激活窗口的行为，保留当前输入焦点。"""
        QWidget.showEvent(self, event)


class FeatureNavigation(QObject):
    """统一管理固定配置、更多浮层、导航选中状态和拖动排序。"""

    def __init__(self, window: MSFluentWindow, toolbox: ToolBoxInterface,
                 features: tuple[Feature, ...]) -> None:
        """注册唯一页面，并根据保存的功能顺序构建导航。"""
        super().__init__(window)
        self.window = window
        self.toolbox = toolbox
        self.features = {feature.key: feature for feature in features}
        self.pinned = list(dict.fromkeys(
            key for key in cfg.sidebarPinnedFeatures.value if key in self.features
        ))
        self.buttons: dict[str, DraggableNavigationButton] = {}
        self.rows: dict[str, FeatureRow] = {}
        self._dragKey: str | None = None
        self._dragPoint = QPoint()
        self._dropIndex = 0
        self._morePersistent = False
        nav = window.navigationInterface
        for feature in features:
            feature.page.setProperty("isStackedTransparent", False)
            window.stackedWidget.addWidget(feature.page)
            button = DraggableNavigationButton(feature, nav)
            nav.addWidget(feature.page.objectName(), button, partial(self.openFeature, feature.key),
                          NavigationItemPosition.SCROLL)
            button.dragMoved.connect(self._dragMoved)
            button.dragFinished.connect(self._dragFinished)
            button.dragCancelled.connect(self._cancelDrag)
            self.buttons[feature.key] = button

        self.moreButton = nav.addItem("featureMore", FluentIcon.MORE, "更多",
                                      self._toggleMore, position=NavigationItemPosition.BOTTOM)
        # 与底部入口间预留一个完整导航按钮位，扣除布局已有的间距。
        gap = max(0, self.moreButton.height() - nav.vBoxLayout.spacing())
        nav.vBoxLayout.insertSpacing(nav.vBoxLayout.indexOf(nav.scrollArea) + 1, gap)
        self.moreButton.setFocusPolicy(Qt.StrongFocus)
        self.moreButton.setAccessibleName("更多功能")
        self._hoverTimer = QTimer(self)
        self._hoverTimer.setSingleShot(True)
        self._hoverTimer.setInterval(250)
        self._hoverTimer.timeout.connect(self.showMore)
        self._leaveTimer = QTimer(self)
        self._leaveTimer.setSingleShot(True)
        self._leaveTimer.setInterval(300)
        self._leaveTimer.timeout.connect(self._closeIfOutside)
        self._pointerTimer = QTimer(self)
        self._pointerTimer.setInterval(50)
        self._pointerTimer.timeout.connect(self._trackHoverPosition)
        self._dragTimer = QTimer(self)
        self._dragTimer.setInterval(60)
        self._dragTimer.timeout.connect(self._scrollDuringDrag)
        self._indicator = QFrame(nav.scrollArea.viewport())
        self._indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._indicator.hide()
        self._buildPopup(features)
        toolbox.setFeatures(features)
        toolbox.featureOpened.connect(self.openFeature)
        toolbox.pinToggled.connect(self.togglePinned)
        window.stackedWidget.currentChanged.connect(self.refreshSelection)
        QApplication.instance().installEventFilter(self)
        self._applyPinned()

    def _buildPopup(self, features: tuple[Feature, ...]) -> None:
        """创建顺序稳定且可滚动的功能浮层。"""
        view = FlyoutViewBase(self.window)
        layout = QVBoxLayout(view)
        layout.setContentsMargins(12, 12, 12, 12)
        self.menuScroll = ScrollArea(view)
        self.menuScroll.setWidgetResizable(True)
        self.menuScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.menuScroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        contentLayout = QVBoxLayout(content)
        contentLayout.setContentsMargins(0, 0, 8, 0)
        previous = ""
        for feature in features:
            if feature.category != previous:
                contentLayout.addWidget(BodyLabel(feature.category, content))
                previous = feature.category
            row = FeatureRow(feature, content)
            row.openButton.clicked.connect(partial(self.openFeature, feature.key))
            row.pinButton.clicked.connect(partial(self.togglePinned, feature.key))
            contentLayout.addWidget(row)
            self.rows[feature.key] = row
        contentLayout.addStretch()
        self.menuScroll.setWidget(content)
        content.setAutoFillBackground(False)
        self.menuScroll.viewport().setAutoFillBackground(False)
        layout.addWidget(self.menuScroll)
        view.setFixedWidth(300)
        self.popup = FeatureFlyout(view, self.window)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """管理悬停开合、键盘打开和窗口变化时的浮层收起。"""
        if self.popup.isVisible():
            if isinstance(event, QMouseEvent) and event.type() == QEvent.MouseButtonPress:
                if not self._containsMoreOrPopup(event.globalPos()):
                    self.popup.hide()
            elif isinstance(event, QKeyEvent) and event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.popup.hide()
                    self.moreButton.setFocus(Qt.OtherFocusReason)
                    return True
            elif event.type() == QEvent.ApplicationDeactivate:
                self.popup.hide()
        if watched is self.moreButton:
            if event.type() == QEvent.Enter:
                self._leaveTimer.stop()
                if not self.popup.isVisible() and self._dragKey is None:
                    self._hoverTimer.start()
            elif event.type() == QEvent.Leave:
                self._hoverTimer.stop()
                self._leaveTimer.start()
            elif isinstance(event, QKeyEvent) and event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                    self._toggleMore()
                    return True
        elif watched is self.popup:
            if event.type() == QEvent.Hide:
                self._morePersistent = False
                self._leaveTimer.stop()
                self._pointerTimer.stop()
            elif event.type() == QEvent.Enter:
                self._leaveTimer.stop()
            elif event.type() == QEvent.Leave:
                self._leaveTimer.start()
        elif watched is self.window and event.type() in (QEvent.Move, QEvent.Resize, QEvent.Hide):
            self._hoverTimer.stop()
            self.popup.hide()
            self._cancelDrag()
        elif watched is self.window and event.type() == QEvent.WindowDeactivate:
            self._hoverTimer.stop()
            self._cancelDrag()
        return super().eventFilter(watched, event)

    def _toggleMore(self) -> None:
        """点击将悬停浮层保持开启，再次点击关闭；键盘操作使用相同规则。"""
        self._hoverTimer.stop()
        self._leaveTimer.stop()
        self.refreshSelection()
        if self._dragKey is not None:
            return
        if self.popup.isVisible() and self._morePersistent:
            self.popup.hide()
        else:
            self.showMore()
            self._morePersistent = self.popup.isVisible()
            self._pointerTimer.stop()

    def showMore(self) -> None:
        """在更多按钮右侧打开浮层并限制在当前屏幕范围内。"""
        self._hoverTimer.stop()
        self._leaveTimer.stop()
        self.refreshSelection()
        if self.popup.isVisible() or self._dragKey is not None:
            return
        screen = self.moreButton.screen().availableGeometry()
        height = min(540, self.window.height() - 70, screen.height() - 40)
        self.menuScroll.setFixedHeight(max(120, height - 52))
        self.popup.adjustSize()
        anchor = self.moreButton.mapToGlobal(QPoint(self.moreButton.width(), 0))
        x = min(anchor.x() + 2, screen.right() - self.popup.width() + 1)
        y = max(screen.top(), min(anchor.y(), screen.bottom() - self.popup.height() + 1))
        self.popup.move(max(screen.left(), x), y)
        self.popup.show()
        self._pointerTimer.start()
        self.refreshSelection()

    def _containsMoreOrPopup(self, point: QPoint) -> bool:
        """统一判断全局鼠标位置是否仍位于按钮或浮层内。"""
        return self.moreButton.rect().contains(self.moreButton.mapFromGlobal(point)) or (
            self.popup.isVisible() and self.popup.rect().contains(self.popup.mapFromGlobal(point))
        )

    def _trackHoverPosition(self) -> None:
        """悬停模式下检查实际鼠标位置，避免漏发离开事件导致菜单常驻。"""
        if self._morePersistent or not self.popup.isVisible():
            return
        if self._containsMoreOrPopup(QCursor.pos()):
            self._leaveTimer.stop()
        elif not self._leaveTimer.isActive():
            self._leaveTimer.start()

    def _closeIfOutside(self) -> None:
        """允许鼠标经过按钮与浮层之间的间隙。"""
        if self._morePersistent:
            return
        if not self._containsMoreOrPopup(QCursor.pos()):
            self.popup.hide()

    def openFeature(self, key: str) -> None:
        """打开已经注册的页面，关闭浮层并同步选中状态。"""
        self._hoverTimer.stop()
        self.popup.hide()
        self.window.switchTo(self.features[key].page)
        self.refreshSelection()

    def togglePinned(self, key: str) -> None:
        """切换固定状态，新固定的功能追加到末尾。"""
        if key in self.pinned:
            self.pinned.remove(key)
        else:
            self.pinned.append(key)
        self._applyPinned()
        cfg.set(cfg.sidebarPinnedFeatures, list(self.pinned))

    def _applyPinned(self) -> None:
        """只重排导航控件，保持页面和路由历史不变。"""
        layout = self.window.navigationInterface.scrollLayout
        for key, button in self.buttons.items():
            layout.removeWidget(button)
            button.hide()
            self.rows[key].setPinned(key in self.pinned)
        for key in self.pinned:
            layout.addWidget(self.buttons[key], 0, Qt.AlignTop | Qt.AlignHCenter)
            self.buttons[key].show()
        self.toolbox.setPinnedFeatures(set(self.pinned))
        self.refreshSelection()

    def refreshSelection(self, index: int = -1) -> None:
        """未固定业务页面归属更多，工具箱仅在其自身页面选中。"""
        page = self.window.stackedWidget.currentWidget()
        if page is None:
            return
        currentKey = next((key for key, feature in self.features.items() if feature.page is page), None)
        route = "featureMore" if currentKey is not None and currentKey not in self.pinned else page.objectName()
        self.window.navigationInterface.setCurrentItem(route)
        for key, row in self.rows.items():
            title = self.features[key].title
            row.openButton.setText(f"{title} · 当前" if key == currentKey else title)

    def _dragMoved(self, key: str, point: QPoint) -> None:
        """计算拖动落点并展示插入线，不提前变更实际顺序。"""
        self._hoverTimer.stop()
        self._leaveTimer.stop()
        self.popup.hide()
        self._dragKey = key
        self._dragPoint = point
        self._dragTimer.start()
        nav = self.window.navigationInterface
        viewport = nav.scrollArea.viewport()
        local = viewport.mapFromGlobal(point)
        if not viewport.rect().contains(local):
            self._indicator.hide()
            return
        others = [candidate for candidate in self.pinned if candidate != key]
        self._dropIndex = len(others)
        y = 2
        for index, candidate in enumerate(others):
            button = self.buttons[candidate]
            top = button.mapTo(viewport, QPoint()).y()
            if local.y() < top + button.height() // 2:
                self._dropIndex = index
                y = top - 2
                break
            y = top + button.height() + 2
        self._indicator.setStyleSheet(f"background: {themeColor().name()}; border-radius: 1px;")
        self._indicator.setGeometry(6, min(max(0, y), viewport.height() - 3), viewport.width() - 12, 3)
        self._indicator.show()
        self._indicator.raise_()

    def _scrollDuringDrag(self) -> None:
        """拖到可视区上下边缘时滚动，以便调整长列表。"""
        if self._dragKey is None:
            return
        area = self.window.navigationInterface.scrollArea
        point = area.viewport().mapFromGlobal(self._dragPoint)
        if not 0 <= point.x() <= area.viewport().width():
            return
        step = -16 if point.y() < 24 else 16 if point.y() > area.viewport().height() - 24 else 0
        if step:
            bar = area.verticalScrollBar()
            bar.setValue(bar.value() + step)
            self._dragMoved(self._dragKey, self._dragPoint)

    def _dragFinished(self, key: str, point: QPoint) -> None:
        """在有效区域释放时保存顺序，否则取消拖动。"""
        self._dragMoved(key, point)
        if self._indicator.isVisible():
            order = [candidate for candidate in self.pinned if candidate != key]
            order.insert(self._dropIndex, key)
            self.pinned = order
            self._applyPinned()
            cfg.set(cfg.sidebarPinnedFeatures, list(self.pinned))
        self._cancelDrag()

    def _cancelDrag(self) -> None:
        """清理拖动提示及自动滚动定时器。"""
        for button in self.buttons.values():
            button.cancelDrag()
        self._dragKey = None
        self._indicator.hide()
        self._dragTimer.stop()
