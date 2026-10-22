from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QWidget
from qfluentwidgets import (
    FluentIconBase, MSFluentWindow, NavigationBar, NavigationBarPushButton,
    NavigationItemPosition,
)
from qfluentwidgets.window.stacked_widget import StackedWidget

from app.ToolBoxInterface import ToolBoxInterface
from app.main_window import MainWindow
from app.utils.config import cfg

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
APP = QApplication.instance() or QApplication([])


class NavigationWindow(QWidget):
    """保留真实导航、堆栈和入口组装，仅替换离屏不兼容的原生窗框。"""

    def __init__(self) -> None:
        """创建无业务网络任务的页面，并运行生产环境的导航初始化。"""
        super().__init__()
        self.resize(900, 671)
        self.navigationInterface = NavigationBar(self)
        self.stackedWidget = StackedWidget(self)
        layout = QHBoxLayout(self)
        layout.addWidget(self.navigationInterface)
        layout.addWidget(self.stackedWidget, 1)
        for name in (
            "home", "schedule", "attendance", "score", "lms", "school_course", "judge",
            "profile", "school_calendar", "campus_card", "venue", "library", "empty_room",
            "fitness", "notice", "ai", "webvpn_convert", "account", "setting", "login", "notice_setting",
        ):
            page = QWidget()
            page.setObjectName(f"{name}Interface")
            setattr(self, f"{name}_interface", page)
        self.tool_box_interface = ToolBoxInterface(self, self)
        MainWindow.initNavigation(self)

    def addSubInterface(self, interface: QWidget, icon: FluentIconBase, text: str,
                        position: NavigationItemPosition = NavigationItemPosition.TOP) -> NavigationBarPushButton:
        """复用组件真实的页面注册与导航按钮创建逻辑。"""
        return MSFluentWindow.addSubInterface(self, interface, icon, text, position=position)

    def switchTo(self, interface: QWidget) -> None:
        """复用生产窗口的堆栈切换。"""
        MSFluentWindow.switchTo(self, interface)

    def _onCurrentInterfaceChanged(self, index: int) -> None:
        """保留基础导航选中和路由更新，随后由业务控制器处理更多归属。"""
        MSFluentWindow._onCurrentInterfaceChanged(self, index)

    def _updateStackedBackground(self) -> None:
        """测试宿主不需要原生窗框背景更新。"""


class FeatureNavigationTest(unittest.TestCase):
    """验证侧栏定制的用户交互、页面状态和配置恢复。"""

    def setUp(self) -> None:
        """将所有配置写入隔离目录，并创建测试窗口。"""
        self.temp = tempfile.TemporaryDirectory(prefix="xjtu-sidebar-test-")
        self.oldFile = cfg.file
        self.oldPinned = list(cfg.sidebarPinnedFeatures.value)
        cfg.file = Path(self.temp.name) / "config.json"
        cfg.sidebarPinnedFeatures.value = list(cfg.sidebarPinnedFeatures.defaultValue)
        self.window = NavigationWindow()
        self.window.show()
        APP.processEvents()
        self.nav = self.window.featureNavigation
        self.toolbox = self.window.tool_box_interface

    def tearDown(self) -> None:
        """停止浮层和定时器，恢复全局配置。"""
        self.nav._cancelDrag()
        self.nav.popup.hide()
        self.window.hide()
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        cfg.file = self.oldFile
        cfg.sidebarPinnedFeatures.value = self.oldPinned
        self.temp.cleanup()

    def test_legacy_defaults_and_shared_unique_pages(self) -> None:
        """旧配置缺少新字段时采用精简布局，全部入口共享唯一页面。"""
        cfg.file.write_text('{"Settings": {"show_avatar_on_sidebar": true}}')
        cfg.load(cfg.file)
        self.assertEqual(self.nav.pinned, ["schedule", "attendance", "score", "lms"])
        self.assertEqual(len(self.nav.features), 16)
        self.assertEqual(self.window.stackedWidget.count(), 22)
        self.assertEqual(len(self.toolbox.cards), 16)
        self.assertNotIn("GitHub", self.window.navigationInterface.items)
        self.assertEqual(self.window.navigationInterface.topLayout.count(), 1)
        self.assertEqual(self.window.navigationInterface.bottomLayout.count(), 4)

    def test_menu_pin_does_not_navigate_or_close_and_unpin_keeps_state(self) -> None:
        """图钉只改变布局，取消当前页面固定不会丢失页面状态。"""
        page = self.nav.features["ai"].page
        edit = QLineEdit(page)
        edit.setText("保留未提交的内容")
        self.nav.showMore()
        APP.processEvents()
        current = self.window.stackedWidget.currentWidget()
        row = self.nav.rows["ai"]
        self.nav.menuScroll.ensureWidgetVisible(row)
        APP.processEvents()
        QTest.mouseClick(row.pinButton, Qt.LeftButton)
        self.assertTrue(self.nav.popup.isVisible())
        self.assertIs(self.window.stackedWidget.currentWidget(), current)
        self.assertEqual(self.nav.pinned[-1], "ai")
        row.openButton.click()
        self.assertIs(self.window.stackedWidget.currentWidget(), page)
        self.assertFalse(self.nav.popup.isVisible())
        self.nav.togglePinned("ai")
        self.assertIs(self.window.stackedWidget.currentWidget(), page)
        self.assertEqual(edit.text(), "保留未提交的内容")
        self.assertTrue(self.nav.moreButton.isSelected)
        self.assertIn("当前", row.openButton.text())
        self.assertEqual(self.window.stackedWidget.count(), 22)

    def test_toolbox_pin_search_and_partition(self) -> None:
        """工具箱图钉不跳转，卡片正确换区，搜索同时覆盖两个区域。"""
        self.window.switchTo(self.toolbox)
        APP.processEvents()
        opened = QSignalSpy(self.toolbox.featureOpened)
        card = self.toolbox.cards["ai"]
        QTest.mouseClick(card.pinButton, Qt.LeftButton)
        APP.processEvents()
        self.assertEqual(len(opened), 0)
        self.assertIs(self.window.stackedWidget.currentWidget(), self.toolbox)
        self.assertTrue(card.pinButton.isChecked())
        group, grid = self.toolbox.groups[True, self.nav.features["ai"].category]
        self.assertIn(card, [grid.gridLayout.itemAt(i).widget() for i in range(grid.gridLayout.count())])
        self.toolbox.searchEdit.setText("空闲")
        APP.processEvents()
        self.assertFalse(self.toolbox.cards["empty_room"].isHidden())
        self.assertTrue(card.isHidden())
        self.assertTrue(self.toolbox.sections[True].isHidden())
        self.toolbox.searchEdit.setText("不存在的功能")
        self.assertFalse(self.toolbox.emptyLabel.isHidden())
        self.toolbox.searchEdit.clear()
        self.assertFalse(card.isHidden())

    def _assertToolboxGeometry(self, expected: set[str]) -> None:
        """检查实际卡片边界，发现零高度容器裁剪和跨分组重叠。"""
        rectangles: dict[str, QRect] = {}
        for key, card in self.toolbox.cards.items():
            if key not in expected:
                self.assertTrue(card.isHidden(), key)
                continue
            self.assertTrue(card.isVisible(), key)
            ancestor = card.parentWidget()
            while ancestor is not None:
                bounds = QRect(card.mapTo(ancestor, QPoint()), card.size())
                self.assertTrue(ancestor.rect().contains(bounds),
                                f"{key} clipped: {bounds} outside {ancestor.rect()}")
                if ancestor is self.toolbox.view:
                    break
                ancestor = ancestor.parentWidget()
            rectangles[key] = QRect(card.mapTo(self.toolbox.view, QPoint()), card.size())
        for key, rect in rectangles.items():
            for otherKey, other in rectangles.items():
                if key < otherKey:
                    self.assertFalse(rect.intersects(other), f"{key} overlaps {otherKey}")

    def test_toolbox_geometry_after_hidden_updates_and_repeated_pin_changes(self) -> None:
        """工具箱隐藏期间换组、连续固定及取消固定后，所有卡片均完整排布。"""
        self.window.switchTo(self.toolbox)
        QTest.qWait(350)
        self._assertToolboxGeometry(set(self.nav.features))
        for key in ("ai", "library", "schedule", "notice", "score", "ai", "library", "schedule"):
            self.window.switchTo(self.nav.features["attendance"].page)
            self.nav.togglePinned(key)
            APP.processEvents()
            self.window.switchTo(self.toolbox)
            QTest.qWait(350)
            self._assertToolboxGeometry(set(self.nav.features))

    def test_toolbox_geometry_after_filter_clear_and_resize(self) -> None:
        """搜索清空后恢复卡片，窗口列数变化不会留下旧位置或裁剪内容。"""
        self.window.switchTo(self.toolbox)
        QTest.qWait(350)
        for width in (1200, 900, 1500, 900):
            self.window.resize(width, 671)
            self.toolbox.searchEdit.setText("空闲")
            QTest.qWait(30)
            self._assertToolboxGeometry({"empty_room"})
            self.toolbox.searchEdit.clear()
            QTest.qWait(30)
            self._assertToolboxGeometry(set(self.nav.features))

    def test_toolbox_columns_shrink_without_refreshing_cards(self) -> None:
        """单纯放大再缩小窗口时，实际列数减少且内容不横向溢出。"""
        self.window.switchTo(self.toolbox)
        QTest.qWait(350)
        category = self.nav.features["campus_card"].category
        _, grid = self.toolbox.groups[False, category]
        for width in (1500, 900, 1200, 900):
            self.window.resize(width, 671)
            QTest.qWait(60)
            available = self.toolbox.viewport().width()
            self.assertLessEqual(self.toolbox.view.width(), available,
                                 "旧列数撑大内容最小宽度，阻止网格收缩")
            margins = self.toolbox.contentLayout.contentsMargins()
            card = self.toolbox.cards["campus_card"]
            expectedColumns = (available - margins.left() - margins.right() + 12) // (card.width() + 12)
            actualColumns = len({self.toolbox.cards[feature.key].x() for feature in self.toolbox.features
                                 if feature.category == category and feature.key not in self.nav.pinned})
            self.assertEqual(actualColumns, expectedColumns)
            self.assertEqual(self.toolbox.horizontalScrollBar().maximum(), 0)
            self._assertToolboxGeometry(set(self.nav.features))

    def test_toolbox_geometry_during_bulk_and_card_pin_changes(self) -> None:
        """连续跨区移动及点击卡片图钉后，卡片不消失、不叠加。"""
        self.window.switchTo(self.toolbox)
        QTest.qWait(350)
        for _ in range(3):
            for key in self.nav.features:
                self.nav.togglePinned(key)
            QTest.qWait(30)
            self._assertToolboxGeometry(set(self.nav.features))
        self.toolbox.searchEdit.setText("问舟")
        QTest.qWait(30)
        for _ in range(4):
            QTest.mouseClick(self.toolbox.cards["ai"].pinButton, Qt.LeftButton)
            QTest.qWait(30)
            self._assertToolboxGeometry({"ai"})
        self.toolbox.searchEdit.clear()
        QTest.qWait(30)
        self._assertToolboxGeometry(set(self.nav.features))

    def test_hovered_card_keeps_new_position_after_reparenting(self) -> None:
        """悬停期间换组后移出鼠标，不允许动画将卡片移回旧分组坐标。"""
        self.window.switchTo(self.toolbox)
        QTest.qWait(350)
        card = self.toolbox.cards["school_calendar"]
        APP.sendEvent(card, QEvent(QEvent.Enter))
        QTest.qWait(120)
        self.nav.togglePinned("school_calendar")
        QTest.qWait(30)
        APP.sendEvent(card, QEvent(QEvent.Leave))
        QTest.qWait(150)
        self._assertToolboxGeometry(set(self.nav.features))

    def test_drag_changes_order_without_opening_page_and_roundtrips(self) -> None:
        """通过真实鼠标事件拖动图标，保存顺序且不触发打开页面。"""
        button = self.nav.buttons["schedule"]
        target = self.nav.buttons["lms"]
        original = self.window.stackedWidget.currentWidget()
        start = button.rect().center()
        end = target.mapToGlobal(QPoint(target.width() // 2, target.height() - 2))
        QTest.mousePress(button, Qt.LeftButton, pos=start)
        move = QMouseEvent(QEvent.MouseMove, button.mapFromGlobal(end), end,
                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        APP.sendEvent(button, move)
        release = QMouseEvent(QEvent.MouseButtonRelease, button.mapFromGlobal(end), end,
                              Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        APP.sendEvent(button, release)
        self.assertEqual(self.nav.pinned, ["attendance", "score", "lms", "schedule"])
        self.assertIs(self.window.stackedWidget.currentWidget(), original)
        cfg.sidebarPinnedFeatures.value = []
        cfg.load(cfg.file)
        self.assertEqual(cfg.sidebarPinnedFeatures.value, self.nav.pinned)

    def test_empty_pins_survive_reload_and_all_pins_keep_anchors_visible(self) -> None:
        """空列表不恢复默认值，全部固定时常用区滚动且固定入口仍可见。"""
        for key in tuple(self.nav.pinned):
            self.nav.togglePinned(key)
        cfg.sidebarPinnedFeatures.value = ["schedule"]
        cfg.load(cfg.file)
        self.assertEqual(cfg.sidebarPinnedFeatures.value, [])
        for key in self.nav.features:
            self.nav.togglePinned(key)
        APP.processEvents()
        area = self.window.navigationInterface.scrollArea
        self.assertGreater(area.verticalScrollBar().maximum(), 0)
        for route in ("featureMore", "toolBoxInterface", "accountInterface", "settingInterface"):
            button = self.window.navigationInterface.widget(route)
            self.assertTrue(button.isVisible())
            self.assertTrue(self.window.rect().contains(button.mapTo(self.window, button.rect().bottomRight())))
        self.assertTrue(self.toolbox.sections[False].isHidden())
        self.assertFalse(self.toolbox.sections[True].isHidden())

    def test_custom_order_restored_and_unknown_ids_ignored(self) -> None:
        """重新创建窗口时恢复自定义顺序，并过滤失效和重复功能。"""
        cfg.set(cfg.sidebarPinnedFeatures, ["ai", "removed_feature", "score", "ai"])
        second = NavigationWindow()
        try:
            self.assertEqual(second.featureNavigation.pinned, ["ai", "score"])
            self.assertFalse(second.featureNavigation.buttons["schedule"].isVisible())
            self.assertEqual(len(second.featureNavigation.rows), 16)
        finally:
            second.deleteLater()
            APP.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_cancel_drag_and_open_unpinned_from_other_entry(self) -> None:
        """取消拖动不改变顺序，主页或托盘直达未固定页时更多正确选中。"""
        button = self.nav.buttons["schedule"]
        original = list(self.nav.pinned)
        current = self.window.stackedWidget.currentWidget()
        QTest.mousePress(button, Qt.LeftButton, pos=button.rect().center())
        end = self.nav.buttons["score"].mapToGlobal(QPoint(20, 20))
        APP.sendEvent(button, QMouseEvent(QEvent.MouseMove, button.mapFromGlobal(end), end,
                                          Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.keyClick(button, Qt.Key_Escape)
        QTest.mouseRelease(button, Qt.LeftButton, pos=button.rect().center())
        self.assertEqual(self.nav.pinned, original)
        self.assertIs(self.window.stackedWidget.currentWidget(), current)
        self.assertFalse(self.nav._indicator.isVisible())
        self.window.switchTo(self.nav.features["ai"].page)
        self.assertTrue(self.nav.moreButton.isSelected)
        self.window.switchTo(self.toolbox)
        self.assertFalse(self.nav.moreButton.isSelected)
        self.assertTrue(self.window.navigationInterface.widget("toolBoxInterface").isSelected)

    def test_drag_scrolls_at_edge_and_rejects_drop_outside(self) -> None:
        """长侧栏支持边缘滚动，拖出常用区释放时不改变顺序。"""
        for key in self.nav.features:
            if key not in self.nav.pinned:
                self.nav.togglePinned(key)
        APP.processEvents()
        area = self.window.navigationInterface.scrollArea
        point = area.viewport().mapToGlobal(QPoint(20, area.viewport().height() - 2))
        self.nav._dragMoved("schedule", point)
        self.nav._scrollDuringDrag()
        self.assertGreater(area.verticalScrollBar().value(), 0)
        original = list(self.nav.pinned)
        self.nav._dragFinished("schedule", self.nav.moreButton.mapToGlobal(QPoint(20, 20)))
        self.assertEqual(self.nav.pinned, original)
        self.assertFalse(self.nav._dragTimer.isActive())

    def test_hover_delay_pointer_bridge_and_keyboard(self) -> None:
        """悬停延迟打开，进入浮层停止关闭，键盘也能访问更多。"""
        APP.sendEvent(self.nav.moreButton, QEvent(QEvent.Enter))
        self.assertFalse(self.nav.popup.isVisible())
        QTest.qWait(300)
        self.assertTrue(self.nav.popup.isVisible())
        APP.sendEvent(self.nav.moreButton, QEvent(QEvent.Leave))
        self.assertTrue(self.nav._leaveTimer.isActive())
        APP.sendEvent(self.nav.popup, QEvent(QEvent.Enter))
        self.assertFalse(self.nav._leaveTimer.isActive())
        with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
            self.nav._closeIfOutside()
        self.assertFalse(self.nav.popup.isVisible())
        QTest.keyClick(self.nav.moreButton, Qt.Key_Return)
        self.assertTrue(self.nav.popup.isVisible())
        with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
            self.nav._closeIfOutside()
        self.assertTrue(self.nav.popup.isVisible())
        QTest.keyClick(self.nav.moreButton, Qt.Key_Return)
        self.assertFalse(self.nav.popup.isVisible())

    def test_hover_popup_click_becomes_persistent_then_closes(self) -> None:
        """浮层不抓取输入，真实按钮首次点击保持展开，第二次点击关闭。"""
        APP.sendEvent(self.nav.moreButton, QEvent(QEvent.Enter))
        QTest.qWait(300)
        self.assertTrue(self.nav.popup.isVisible())
        self.assertIsNone(APP.activePopupWidget(), "浮层不能接管侧栏的鼠标事件")
        point = self.nav.moreButton.mapTo(self.window, self.nav.moreButton.rect().center())
        for expected in (True, False):
            QTest.mouseClick(self.window.windowHandle(), Qt.LeftButton, pos=point)
            APP.sendEvent(self.nav.popup, QEvent(QEvent.Leave))
            with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
                QTest.qWait(350)
            self.assertEqual(self.nav.popup.isVisible(), expected)
        APP.sendEvent(self.nav.moreButton, QEvent(QEvent.Enter))
        QTest.qWait(300)
        self.assertTrue(self.nav.popup.isVisible())
        with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
            self.nav._closeIfOutside()
        self.assertFalse(self.nav.popup.isVisible())

    def test_hover_closes_in_every_direction_without_leave_event(self) -> None:
        """即使没有 Leave 事件，沿侧栏上下左右移出按钮也会自动收起。"""
        button = self.nav.moreButton
        for local in (QPoint(20, -10), QPoint(20, button.height() + 10),
                      QPoint(-10, 20), QPoint(500, 20)):
            point = button.mapToGlobal(local)
            with patch("app.components.feature_navigation.QCursor.pos", return_value=point):
                self.nav.showMore()
                self.assertTrue(self.nav.popup.isVisible())
                self.assertFalse(self.nav._containsMoreOrPopup(point))
                QTest.qWait(450)
                self.assertFalse(self.nav.popup.isVisible(), str(local))
                self.assertFalse(self.nav._pointerTimer.isActive())

    def test_hover_pointer_bridge_cancels_delayed_close_without_enter_event(self) -> None:
        """鼠标经过间隙进入菜单时，即使未收到 Enter 也取消延迟关闭。"""
        with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
            self.nav.showMore()
            QTest.qWait(100)
            self.assertTrue(self.nav._leaveTimer.isActive())
        inside = self.nav.popup.mapToGlobal(self.nav.popup.rect().center())
        with patch("app.components.feature_navigation.QCursor.pos", return_value=inside):
            QTest.qWait(400)
            self.assertTrue(self.nav.popup.isVisible())
            self.assertFalse(self.nav._leaveTimer.isActive())

    def test_nonmodal_popup_dismisses_on_outside_click_escape_and_deactivation(self) -> None:
        """非模态浮层仍支持外部点击、Esc 和切换应用关闭，且不吞掉底层点击。"""
        self.nav.moreButton.click()
        QTest.mouseClick(self.nav.buttons["score"], Qt.LeftButton)
        self.assertFalse(self.nav.popup.isVisible())
        self.assertIs(self.window.stackedWidget.currentWidget(), self.nav.features["score"].page)
        self.nav.moreButton.click()
        QTest.keyClick(self.nav.rows["score"].openButton, Qt.Key_Escape)
        self.assertFalse(self.nav.popup.isVisible())
        self.nav.moreButton.click()
        APP.sendEvent(APP, QEvent(QEvent.ApplicationDeactivate))
        self.assertFalse(self.nav.popup.isVisible())

    def test_persistent_popup_resets_after_navigation_or_dismissal(self) -> None:
        """跳转或外部关闭后清除保持状态，下次悬停仍可自动收起。"""
        for navigate in (True, False):
            self.nav.moreButton.click()
            self.nav.rows["ai"].pinButton.click()
            with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
                self.nav._closeIfOutside()
            self.assertTrue(self.nav.popup.isVisible())
            if navigate:
                self.nav.rows["ai"].openButton.click()
            else:
                self.nav.popup.close()
            self.assertFalse(self.nav.popup.isVisible())
            self.nav.showMore()
            with patch("app.components.feature_navigation.QCursor.pos", return_value=QPoint(-10000, -10000)):
                self.nav._closeIfOutside()
            self.assertFalse(self.nav.popup.isVisible())

    def test_repeated_more_click_preserves_current_page_selection(self) -> None:
        """重复打开更多时，选中标记仍对应实际页面。"""
        self.window.switchTo(self.toolbox)
        for expected in (True, False, True):
            self.nav.moreButton.click()
            self.assertEqual(self.nav.popup.isVisible(), expected)
            self.assertFalse(self.nav.moreButton.isSelected)
            self.assertTrue(self.window.navigationInterface.widget("toolBoxInterface").isSelected)

    def test_resize_cancels_drag_until_mouse_release(self) -> None:
        """调整窗口大小取消拖动后，释放鼠标不重新提交排序或触发导航。"""
        button = self.nav.buttons["schedule"]
        original = list(self.nav.pinned)
        page = self.window.stackedWidget.currentWidget()
        QTest.mousePress(button, Qt.LeftButton, pos=button.rect().center())
        end = self.nav.buttons["lms"].mapToGlobal(QPoint(20, 56))
        APP.sendEvent(button, QMouseEvent(QEvent.MouseMove, button.mapFromGlobal(end), end,
                                          Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        self.window.resize(950, 671)
        APP.processEvents()
        APP.sendEvent(button, QMouseEvent(QEvent.MouseButtonRelease, button.mapFromGlobal(end), end,
                                          Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(self.nav.pinned, original)
        self.assertIs(self.window.stackedWidget.currentWidget(), page)

    def test_dragging_over_more_does_not_open_popup(self) -> None:
        """拖动经过更多时不打开会抢占鼠标的浮层。"""
        button = self.nav.buttons["schedule"]
        QTest.mousePress(button, Qt.LeftButton, pos=button.rect().center())
        end = self.nav.moreButton.mapToGlobal(QPoint(20, 20))
        APP.sendEvent(button, QMouseEvent(QEvent.MouseMove, button.mapFromGlobal(end), end,
                                          Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        APP.sendEvent(self.nav.moreButton, QEvent(QEvent.Enter))
        QTest.qWait(300)
        self.assertFalse(self.nav.popup.isVisible())
        QTest.keyClick(button, Qt.Key_Escape)

    def test_all_sidebar_labels_fit_and_keep_full_accessible_name(self) -> None:
        """固定长名称功能后，侧栏文字完整可读，提示和无障碍名称仍用全名。"""
        for key, feature in self.nav.features.items():
            if key not in self.nav.pinned:
                self.nav.togglePinned(key)
            button = self.nav.buttons[key]
            self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()), button.width() - 8, key)
            self.assertEqual(button.accessibleName(), feature.title)
            self.assertIn(feature.title, button.toolTip())


if __name__ == "__main__":
    unittest.main()
