import datetime
import gc
import json
import locale
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_STATE_HOME", "/tmp/xjtu-test-state")
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/xjtu-test-config")

from PyQt5.QtCore import Qt, QRect, QThread
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

from qfluentwidgets import (
    EditableComboBox,
    PopUpAniStackedWidget,
    SearchLineEdit,
    Theme,
    TreeWidget,
    setTheme,
)

from ai_assistant import AIConfigStore, ChatMessage, PRESETS, ProviderConfig, collect_local_context
from ai_assistant.markdown_render import render_markdown_fragment
from app.AIInterface import (
    AIInterface,
    _AIRequestFailure,
    _AIRequestOutcome,
    _AIRequestThread,
)
from app.components.NoticeCard import NoticeCard
from app.components.NoticeRuleCard import NoticeRuleCard
from app.components.NoticeSourceCard import NoticeSourceCard
from app.sub_interfaces.NoticeChoiceInterface import NoticeChoiceInterface
from app.sub_interfaces.NoticeInterface import NoticeInterface
from app.sub_interfaces.NoticeSettingInterface import NoticeSettingInterface
from app.utils.cache import cacheManager
from notification import Notification, NotificationManager, Ruleset
from notification.filter import TitleIncludeFilter
from notification.crawlers.generic import parse_publication_date


app = QApplication.instance() or QApplication([])


class DummyMainWindow:
    notice_setting_interface = None

    def switchTo(self, _interface):
        pass

    def isVisible(self):
        return True


class DummyKeyring:
    def get_password(self, *_args):
        return None

    def set_password(self, *_args):
        return None

    def delete_password(self, *_args):
        return None


class NoticeChoiceUITest(unittest.TestCase):
    def create_widget(self, manager=None):
        widget = NoticeChoiceInterface(manager or NotificationManager([]), DummyMainWindow())
        widget.resize(900, 650)
        widget.show()
        app.processEvents()
        self.addCleanup(widget.close)
        return widget

    def test_date_parser_is_locale_independent_after_qapplication(self):
        self.assertIsNotNone(QApplication.instance())
        original_locale = locale.setlocale(locale.LC_TIME)
        try:
            for locale_name in ("zh_CN.UTF-8", "zh_CN.utf8", "Chinese_China.936"):
                try:
                    locale.setlocale(locale.LC_TIME, locale_name)
                    break
                except locale.Error:
                    continue
            with patch("notification.crawlers.generic.datetime.datetime") as strptime:
                strptime.strptime.side_effect = AssertionError("date parser must not use LC_TIME")
                cases = {
                    "08/03 2026": datetime.date(2026, 8, 3),
                    "03 Aug 2026": datetime.date(2026, 8, 3),
                    "Aug 03 2026": datetime.date(2026, 8, 3),
                    "3 August 2026": datetime.date(2026, 8, 3),
                    "August 3 2026": datetime.date(2026, 8, 3),
                }
                for value, expected in cases.items():
                    with self.subTest(value=value):
                        self.assertEqual(parse_publication_date([value]), expected)
                strptime.strptime.assert_not_called()
        finally:
            locale.setlocale(locale.LC_TIME, original_locale)

    def test_uses_fluent_tree_search_and_three_disciplines(self):
        widget = self.create_widget()
        self.assertIsInstance(widget.searchEdit, SearchLineEdit)
        self.assertIsInstance(widget.tree, TreeWidget)
        root = widget.tree.topLevelItem(0)
        college = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == "学院与学部")
        disciplines = {college.child(i).text(0) for i in range(college.childCount())}
        self.assertEqual(disciplines, {"工学", "理学", "人文经管"})

    def test_only_xjtu_root_is_expanded_by_default(self):
        widget = self.create_widget()
        roots = [
            widget.tree.topLevelItem(index)
            for index in range(widget.tree.topLevelItemCount())
        ]
        xjtu = next(item for item in roots if item.text(0) == "西安交通大学")
        self.assertTrue(xjtu.isExpanded())

        def descendants(item):
            for index in range(item.childCount()):
                child = item.child(index)
                yield child
                yield from descendants(child)

        self.assertTrue(all(not item.isExpanded() for item in descendants(xjtu)))
        self.assertTrue(all(not item.isExpanded() for item in roots if item is not xjtu))

    def test_expansion_keeps_header_geometry_stable(self):
        widget = self.create_widget()
        before = (
            widget.searchEdit.mapTo(widget, widget.searchEdit.rect().topLeft()),
            widget.sizeHint().height(),
            widget.height(),
        )
        for site in widget.siteItems.values():
            site.setExpanded(not site.isExpanded())
        for index in range(widget.tree.topLevelItemCount()):
            widget.tree.expandItem(widget.tree.topLevelItem(index))
        app.processEvents()
        after = (
            widget.searchEdit.mapTo(widget, widget.searchEdit.rect().topLeft()),
            widget.sizeHint().height(),
            widget.height(),
        )
        self.assertEqual(before, after)

    def test_parent_child_round_trip_writes_exact_subscriptions(self):
        manager = NotificationManager([])
        widget = self.create_widget(manager)
        parent = widget.siteItems["gs"]
        parent.setCheckState(0, Qt.Checked)
        app.processEvents()
        self.assertEqual(parent.checkState(0), Qt.Checked)
        self.assertEqual(len([one for one in manager.subscription if one.startswith("gs/")]), 6)

        parent.child(0).setCheckState(0, Qt.Unchecked)
        app.processEvents()
        self.assertEqual(parent.checkState(0), Qt.PartiallyChecked)
        self.assertEqual(len([one for one in manager.subscription if one.startswith("gs/")]), 5)

        parent.setCheckState(0, Qt.Unchecked)
        app.processEvents()
        self.assertEqual(parent.checkState(0), Qt.Unchecked)
        self.assertFalse(any(one.startswith("gs/") for one in manager.subscription))

    def test_cross_listed_college_and_academy_share_one_subscription(self):
        manager = NotificationManager([])
        widget = self.create_widget(manager)
        copies = widget._sourceItemCopies["bjb/tzgg"]
        self.assertEqual({item.text(0) for item in copies}, {"钱学森学院", "钱学森书院"})
        college = next(item for item in copies if item.text(0) == "钱学森学院")
        academy = next(item for item in copies if item.text(0) == "钱学森书院")

        academy.setCheckState(0, Qt.Checked)
        app.processEvents()
        self.assertEqual(manager.subscription.count("bjb/tzgg"), 1)
        self.assertEqual(college.checkState(0), Qt.Checked)
        self.assertEqual(academy.checkState(0), Qt.Checked)

        academy.setCheckState(0, Qt.Unchecked)
        app.processEvents()
        self.assertNotIn("bjb/tzgg", manager.subscription)
        self.assertEqual(college.checkState(0), Qt.Unchecked)

        college.setCheckState(0, Qt.Checked)
        app.processEvents()
        self.assertEqual(manager.subscription.count("bjb/tzgg"), 1)
        self.assertEqual(academy.checkState(0), Qt.Checked)

    def test_fuzzy_search_filters_and_clear_restores_tree(self):
        widget = self.create_widget()
        widget.searchEdit.setText("储能 教学")
        app.processEvents()
        self.assertFalse(widget.sourceItems["gjcnpt/jxyx"].isHidden())
        self.assertTrue(widget.sourceItems["math/bkspy"].isHidden())
        widget.searchEdit.clear()
        app.processEvents()
        self.assertTrue(all(not item.isHidden() for item in widget.sourceItems.values()))

    def test_search_uses_each_cross_listed_display_name(self):
        widget = self.create_widget()
        academy = next(
            item for item in widget._sourceItemCopies["bjb/tzgg"] if item.text(0) == "钱学森书院"
        )
        college = next(
            item for item in widget._sourceItemCopies["bjb/tzgg"] if item.text(0) == "钱学森学院"
        )
        widget.searchEdit.setText("钱学森书院")
        app.processEvents()
        self.assertFalse(academy.isHidden())
        self.assertTrue(college.isHidden())

    def test_dean_is_flat_and_real_prefix_categories_are_usable_filters(self):
        manager = NotificationManager(["dean/jxtz"])
        widget = self.create_widget(manager)
        dean = widget.sourceItems["dean/jxtz"]
        self.assertEqual(dean.text(0), "教务处")
        self.assertNotIn("教学通知", dean.text(1))
        self.assertNotIn("dean", widget.siteItems)
        categories = {dean.child(index).text(0) for index in range(dean.childCount())}
        self.assertIn("竞赛大创", categories)
        self.assertNotIn("[竞赛大创]", categories)
        competition = next(
            dean.child(index) for index in range(dean.childCount())
            if dean.child(index).text(0) == "竞赛大创"
        )
        self.assertIn("“竞赛大创”", competition.toolTip(0))
        self.assertNotIn("[", competition.toolTip(0))
        competition.setCheckState(0, Qt.Checked)
        app.processEvents()
        self.assertTrue(manager.ruleset["dean/jxtz"])
        self.assertTrue(manager.satisfy_filter(Notification(
            "大创通知", "https://example.test/1", "dean/jxtz", tags={"竞赛大创"}
        )))
        self.assertFalse(manager.satisfy_filter(Notification(
            "考试通知", "https://example.test/2", "dean/jxtz", tags={"考试安排"}
        )))


class NoticeListSearchUITest(unittest.TestCase):
    def test_notice_list_reuses_search_module_for_title_source_tag_and_empty_query(self):
        with patch.object(NoticeInterface, "load_or_create_manager", return_value=NotificationManager([])), \
             patch.object(cacheManager, "read_json", return_value=[]):
            widget = NoticeInterface(DummyMainWindow())
        self.addCleanup(widget.close)
        widget.show()
        notices = [
            Notification("医学部暑假值班表", "https://example.test/1", "med/tzgg", tags={"值班"}),
            Notification("电气学院研究生通知", "https://example.test/2", "ee/yjs", tags={"研究生"}),
        ]
        widget.notices = notices
        for notice in notices:
            card = NoticeCard(notice, widget.noticeFrame)
            widget.noticeWidgets.append(card)
            widget.noticeFrameLayout.addWidget(card)
        widget.searchEdit.setText("医学 值班")
        app.processEvents()
        self.assertFalse(widget.noticeWidgets[0].isHidden())
        self.assertTrue(widget.noticeWidgets[1].isHidden())
        widget.searchEdit.setText("研究生")
        app.processEvents()
        self.assertTrue(widget.noticeWidgets[0].isHidden())
        self.assertFalse(widget.noticeWidgets[1].isHidden())
        widget.searchEdit.clear()
        app.processEvents()
        self.assertTrue(all(not card.isHidden() for card in widget.noticeWidgets))


class NoticeResponsiveGeometryTest(unittest.TestCase):
    @staticmethod
    def rect_in(widget, ancestor):
        top_left = widget.mapTo(ancestor, widget.rect().topLeft())
        return QRect(top_left, widget.size())

    def assert_inside(self, child, parent):
        child_rect = self.rect_in(child, parent)
        self.assertGreaterEqual(child_rect.left(), 0)
        self.assertGreaterEqual(child_rect.top(), 0)
        self.assertLessEqual(child_rect.right(), parent.rect().right())
        self.assertLessEqual(child_rect.bottom(), parent.rect().bottom())

    def test_long_notice_card_keeps_text_and_menu_separate_at_narrow_width(self):
        notice = Notification(
            "这是一条用于验证极端长标题不会覆盖更多操作按钮的通知" * 4,
            "https://example.test/notice",
            "med/tzgg",
            tags={"本科生教学", "研究生培养", "国际交流", "非常长的标签"},
        )
        card = NoticeCard(notice)
        card.resize(360, card.sizeHint().height())
        card.show()
        app.processEvents()
        self.addCleanup(card.close)
        self.assert_inside(card.moreButton, card)
        self.assert_inside(card.titleLabel, card)
        self.assert_inside(card.contentLabel, card)
        self.assertFalse(
            self.rect_in(card.moreButton, card).intersects(self.rect_in(card.titleLabel, card))
        )
        self.assertFalse(
            self.rect_in(card.moreButton, card).intersects(self.rect_in(card.contentLabel, card))
        )

    def test_source_link_and_filter_buttons_have_independent_cells_at_narrow_width(self):
        widget = NoticeChoiceInterface(
            NotificationManager(["dean/jxtz"]), DummyMainWindow()
        )
        self.addCleanup(widget.close)
        for width in (520, 876):
            widget.resize(width, 520)
            item = widget.sourceItems["dean/jxtz"]
            cursor = item
            while cursor is not None:
                cursor.setExpanded(True)
                cursor = cursor.parent()
            widget.show()
            widget.tree.scrollToItem(item)
            app.processEvents()
            container = widget.tree.itemWidget(item, 2)
            buttons = container.findChildren(type(widget.ruleButtons["dean/jxtz"]))
            self.assertEqual(len(buttons), 2)
            self.assertGreaterEqual(widget.tree.visualItemRect(item).height(), 40)
            self.assertEqual(widget.tree.columnWidth(2), widget.ACTION_COLUMN_WIDTH)
            for button in buttons:
                self.assert_inside(button, container)
            self.assertFalse(
                self.rect_in(buttons[0], container).intersects(
                    self.rect_in(buttons[1], container)
                )
            )

    def test_source_jump_filter_and_rule_actions_are_on_separate_rows(self):
        source_card = NoticeSourceCard("gs/zsgz", checked=True)
        ruleset = Ruleset(
            TitleIncludeFilter("极端长过滤关键词" * 5),
            name="极端长规则名称" * 5,
        )
        rule_card = NoticeRuleCard(ruleset)
        for card in (source_card, rule_card):
            card.resize(360, card.sizeHint().height())
            card.show()
            self.addCleanup(card.close)
        app.processEvents()

        for button in (source_card.browseButton, source_card.addRuleButton):
            self.assert_inside(button, source_card)
            self.assertFalse(
                self.rect_in(button, source_card).intersects(
                    self.rect_in(source_card.contentLabel, source_card)
                )
            )
        self.assertFalse(
            self.rect_in(source_card.browseButton, source_card).intersects(
                self.rect_in(source_card.addRuleButton, source_card)
            )
        )
        for button in (rule_card.editButton, rule_card.enableButton, rule_card.deleteButton):
            self.assert_inside(button, rule_card)
            self.assertFalse(
                self.rect_in(button, rule_card).intersects(
                    self.rect_in(rule_card.contentLabel, rule_card)
                )
            )

    def test_notice_toolbar_search_filter_progress_and_cards_do_not_overlap(self):
        with patch.object(NoticeInterface, "load_or_create_manager", return_value=NotificationManager([])), \
             patch.object(cacheManager, "read_json", return_value=[]):
            widget = NoticeInterface(DummyMainWindow())
        self.addCleanup(widget.close)
        widget.resize(520, 640)
        widget.filterHintLabel.setVisible(True)
        widget.searchResultLabel.setText("找到 1 / 2 条通知")
        widget.searchResultLabel.setVisible(True)
        widget.processWidget.setVisible(True)
        card = NoticeCard(
            Notification("长通知标题" * 18, "https://example.test/1", "med/tzgg", tags={"长标签" * 6}),
            widget.noticeFrame,
        )
        widget.noticeWidgets.append(card)
        widget.noticeFrameLayout.addWidget(card)
        widget.switchTo(widget.noticeFrame)
        widget.show()
        app.processEvents()

        ordered = [widget.commandBar, widget.searchEdit, widget.processWidget, widget.noticeFrame]
        rects = [self.rect_in(one, widget.view) for one in ordered]
        for earlier, later in zip(rects, rects[1:]):
            self.assertLess(earlier.bottom(), later.top())
        for control in (widget.commandBar, widget.searchEdit, widget.processWidget):
            rect = self.rect_in(control, widget.view)
            self.assertGreaterEqual(rect.left(), 0)
            self.assertLessEqual(rect.right(), widget.view.rect().right())
        self.assertLessEqual(card.width(), widget.noticeFrame.width())
        self.assertLessEqual(card.geometry().top(), 1)

    def test_breadcrumb_choice_filter_and_rule_editor_remain_separate(self):
        manager = NotificationManager(["gs/zsgz"])
        with patch.object(NoticeInterface, "load_or_create_manager", return_value=manager), \
             patch.object(cacheManager, "read_json", return_value=[]):
            notice = NoticeInterface(DummyMainWindow())
        setting = NoticeSettingInterface(manager, notice)
        notice.main_window.notice_setting_interface = setting
        self.addCleanup(setting.close)
        self.addCleanup(notice.close)
        setting.resize(600, 640)
        setting.show()
        app.processEvents()

        breadcrumb = self.rect_in(setting.breadcrumbBar, setting.view)
        stack = self.rect_in(setting.stackedWidget, setting.view)
        self.assertLess(breadcrumb.bottom(), stack.top())
        choice = setting.choiceInterface
        self.assertLess(
            self.rect_in(choice.searchEdit, choice).bottom(),
            self.rect_in(choice.tree, choice).top(),
        )
        self.assertLess(
            self.rect_in(choice.tree, choice).bottom(),
            self.rect_in(choice.returnButton, choice).top(),
        )

        setting.onModifyRuleClicked("gs/zsgz")
        app.processEvents()
        self.assertIs(setting.stackedWidget.currentWidget(), setting.ruleInterface)
        rule = setting.ruleInterface
        self.assertFalse(
            self.rect_in(rule.titleLabel, rule).intersects(
                self.rect_in(rule.addRuleCard, rule)
            )
        )
        self.assert_inside(rule.completeButton, rule)

        setting.onRuleSetClicked(Ruleset(), "gs/zsgz")
        app.processEvents()
        editor = setting.ruleSetInterface
        self.assertIs(setting.stackedWidget.currentWidget(), editor)
        self.assertFalse(
            self.rect_in(editor.nameEdit, editor).intersects(
                self.rect_in(editor.addButton, editor)
            )
        )
        self.assert_inside(editor.completeButton, editor)


class AIInterfaceSmokeTest(unittest.TestCase):
    def create_interfaces(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        widget = AIInterface(config_store=AIConfigStore(
            Path(temporary.name) / "profiles.json", keyring_backend=DummyKeyring()
        ))
        widget.resize(800, 640)
        widget.show()
        app.processEvents()
        self.addCleanup(widget.close)
        return widget

    def test_interface_constructs_without_school_ai_entry(self):
        widget = self.create_interfaces()
        self.assertEqual(widget.objectName(), "AIInterface")
        import app.main_window as main_window

        self.assertFalse(hasattr(main_window, "open_school_ai_in_system_browser"))
        self.assertNotIn("app.school_ai_browser", sys.modules)
        self.assertNotIn("app.school_ai_launcher", sys.modules)
        self.assertNotIn("PyQt6", sys.modules)

    def test_provider_is_quick_config_but_protocol_remains_independent(self):
        widget = self.create_interfaces()
        deepseek_index = next(i for i, preset in enumerate(PRESETS) if preset.id == "deepseek")
        widget.presetCombo.setCurrentIndex(deepseek_index)
        anthropic_protocol = next(i for i, one in enumerate(widget.PROTOCOLS) if one[0] == "anthropic")
        widget.protocolCombo.setCurrentIndex(anthropic_protocol)
        app.processEvents()
        self.assertEqual(widget._currentPreset().id, "deepseek")
        self.assertEqual(widget._currentProtocol(), "anthropic")
        self.assertTrue(widget.saveConfiguration())
        self.assertEqual(widget.profile.protocol, "anthropic")
        self.assertEqual(widget.profile.preset_id, "deepseek")
        self.assertEqual(widget._providerConfig().protocol, "anthropic")

    def test_capabilities_default_off_and_only_explicit_selection_is_saved(self):
        widget = self.create_interfaces()
        self.assertTrue(all(not checkbox.isChecked() for checkbox in widget.capabilityChecks.values()))
        self.assertFalse(widget.searchEngineCombo.isEnabled())
        widget.capabilityChecks["schedule"].setChecked(True)
        self.assertTrue(widget.saveConfiguration())
        self.assertEqual(widget.profile.capability_ids, ("schedule",))
        widget.capabilityChecks["web_search"].setChecked(True)
        searxng_index = widget.searchEngineCombo.findText("SearXNG（聚合）")
        widget.searchEngineCombo.setCurrentIndex(searxng_index)
        widget.searchEndpointEdit.setText("https://search.example")
        self.assertTrue(widget.searchEndpointEdit.isEnabled())
        self.assertTrue(widget.saveConfiguration())
        self.assertEqual(widget.profile.search_engine, "searxng")
        self.assertEqual(widget.profile.search_endpoint, "https://search.example")

    def test_mainstream_search_choice_persists_and_captcha_turns_capability_off(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            first = AIInterface(config_store=AIConfigStore(path, keyring_backend=DummyKeyring()))
            self.addCleanup(first.close)
            first.capabilityChecks["web_search"].setChecked(True)
            google = first.searchEngineCombo.findText("Google（通过 SearXNG）")
            first.searchEngineCombo.setCurrentIndex(google)
            first.searchEndpointEdit.setText("https://search.example")
            first.searchEndpointEdit.editingFinished.emit()
            first.searchLimitCombo.setCurrentText("8")
            app.processEvents()
            second = AIInterface(config_store=AIConfigStore(path, keyring_backend=DummyKeyring()))
            self.addCleanup(second.close)
            self.assertEqual(second._currentSearchEngine(), "google")
            self.assertEqual(second.searchEndpointEdit.text(), "https://search.example/")
            self.assertEqual(second.searchLimitCombo.currentText(), "8")
            self.assertTrue(second.capabilityChecks["web_search"].isChecked())

            with patch("app.AIInterface.InfoBar.warning"):
                second._onWebSearchDisabled(_AIRequestFailure("DuckDuckGo 要求人机验证", "session"))
            self.assertFalse(second.capabilityChecks["web_search"].isChecked())
            reloaded = AIConfigStore(path, keyring_backend=DummyKeyring()).load_profiles()[0]
            self.assertNotIn("web_search", reloaded.capability_ids)

    def test_model_dropdown_download_guard_markdown_status_and_placeholder(self):
        widget = self.create_interfaces()
        self.assertIsInstance(widget.modelCombo, EditableComboBox)
        self.assertFalse(widget.downloadModelButton.isEnabled())
        ollama_protocol = next(i for i, one in enumerate(widget.PROTOCOLS) if one[0] == "ollama")
        widget.protocolCombo.setCurrentIndex(ollama_protocol)
        app.processEvents()
        self.assertTrue(widget.downloadModelButton.isEnabled())
        self.assertTrue(widget.modelCombo.dropButton.isVisible())

        widget._onModelsLoaded(["gemma3", "qwen3:8b"])
        self.assertEqual(widget.modelCombo.count(), 3)
        self.assertIn("右侧箭头", widget.modelStatusLabel.text())
        with patch.object(widget, "refreshModels") as refresh_models, \
             patch("app.AIInterface.QTimer.singleShot", side_effect=lambda _delay, callback: callback()):
            widget._onModelPullSucceeded("qwen3:8b")
        self.assertEqual(widget.modelCombo.currentText(), "qwen3:8b")
        refresh_models.assert_called_once_with()

        fragment = render_markdown_fragment(
            "# 标题\n\n- **粗体**\n\n```python\nprint('ok')\n```\n\n"
            "<script>alert(1)</script> ![track](https://evil.test/pixel.png)"
        )
        self.assertIn("<h1>", fragment)
        self.assertIn("<pre>", fragment)
        self.assertNotIn("<script", fragment)
        self.assertNotIn("<img", fragment)
        widget.messages = [ChatMessage("assistant", "# 标题\n\n- 项目")]
        widget.assistantMeta = [{}]
        widget._renderTranscript()
        self.assertIn("标题", widget.transcript.toPlainText())

        widget._requestState = "thinking"
        widget._requestStarted = time.monotonic() - widget.STUCK_SECONDS - 1
        widget._lastTickSecond = -1
        widget._onRequestTick()
        self.assertEqual(widget._requestState, "stuck")
        self.assertIn("秒", widget.statusLabel.text())
        self.assertIn("可能", widget.statusLabel.text())
        self.assertEqual(widget.inputEdit.placeholderText(), "输入消息…")
        self.assertNotIn("不是学校", widget.inputEdit.placeholderText())

    def test_request_success_and_failure_states_both_report_real_elapsed_time(self):
        widget = self.create_interfaces()
        widget._requestStarted = time.monotonic() - 1.2
        widget._onResult(SimpleNamespace(result=SimpleNamespace(
            text="**完成**",
            model="test-model",
            input_tokens=3,
            output_tokens=2,
        ), search_count=1))
        self.assertEqual(widget._requestState, "done")
        self.assertIn("回答完成", widget.statusLabel.text())
        self.assertIn("秒", widget.statusLabel.text())
        self.assertIn("完成", widget.transcript.toPlainText())
        self.assertIn("test-model", widget.transcript.toPlainText())

        widget._requestStarted = time.monotonic() - 2.1
        with patch("app.AIInterface.InfoBar.error"):
            widget._onError("模拟服务失败")
        self.assertEqual(widget._requestState, "error")
        self.assertIn("请求失败", widget.statusLabel.text())
        self.assertIn("秒", widget.statusLabel.text())
        self.assertIn("模拟服务失败", widget.transcript.toPlainText())

    def test_finished_background_threads_release_references_for_repeated_actions(self):
        widget = self.create_interfaces()

        stale = QThread(widget)
        current = QThread(widget)
        widget.modelListThread = current
        widget.refreshModelsButton.setEnabled(False)
        widget._onModelListFinished(stale)
        self.assertIs(widget.modelListThread, current)
        widget._onModelListFinished(current)
        self.assertIsNone(widget.modelListThread)
        self.assertTrue(widget.refreshModelsButton.isEnabled())

        current = QThread(widget)
        widget.modelPullThread = current
        widget.downloadModelButton.setText("取消下载")
        widget.modelProgress.setRange(0, 0)
        widget._onModelPullFinished(current)
        self.assertIsNone(widget.modelPullThread)
        self.assertEqual(widget.downloadModelButton.text(), "下载模型")
        self.assertEqual(widget.modelProgress.maximum(), 100)

        current = QThread(widget)
        widget.requestThread = current
        widget.sendButton.setEnabled(False)
        widget.clearButton.setEnabled(False)
        widget.cancelButton.setVisible(True)
        widget._onFinished(current)
        self.assertIsNone(widget.requestThread)
        self.assertTrue(widget.sendButton.isEnabled())
        self.assertTrue(widget.clearButton.isEnabled())
        self.assertFalse(widget.cancelButton.isVisible())

    def test_compact_window_keeps_settings_chat_and_input_in_order(self):
        widget = self.create_interfaces()
        self.assertEqual(widget.size(), widget.size().boundedTo(widget.maximumSize()))
        settings_bottom = widget.settingsStack.geometry().bottom()
        chat_top = widget.chatCard.geometry().top()
        chat_bottom = widget.chatCard.geometry().bottom()
        input_top = widget.inputEdit.geometry().top()
        self.assertLess(settings_bottom, chat_top)
        self.assertLess(chat_bottom, input_top)
        self.assertGreaterEqual(widget.chatCard.height(), widget.transcript.minimumHeight())

    def test_config_controls_keep_natural_height_at_narrow_and_normal_widths(self):
        widget = self.create_interfaces()
        controls = (
            widget.presetCombo, widget.protocolCombo, widget.baseUrlEdit,
            widget.modelCombo, widget.refreshModelsButton, widget.downloadModelButton,
            widget.apiKeyEdit, widget.saveButton,
        )
        for width in (640, 900):
            widget.resize(width, 760)
            widget._refreshSettingsHeight()
            app.processEvents()
            self.assertGreaterEqual(
                widget.configCard.height(), widget.configCard.sizeHint().height()
            )
            for control in controls:
                self.assertGreaterEqual(
                    control.height(), control.sizeHint().height(),
                    f"{type(control).__name__} was vertically compressed at {width}px",
                )

    def test_default_combined_page_animates_to_expanded_page_and_sessions_switch(self):
        widget = self.create_interfaces()
        self.assertIsInstance(widget.pageStack, PopUpAniStackedWidget)
        self.assertIs(widget.pageStack.currentWidget(), widget.compactPage)
        widget.inputEdit.setPlainText("未发送草稿")
        widget.pageStack.setAnimationEnabled(False)
        widget.showExpandedConversation()
        self.assertIs(widget.pageStack.currentWidget(), widget.expandedPage)
        self.assertEqual(widget.expandedInputEdit.toPlainText(), "未发送草稿")
        widget.expandedInputEdit.setPlainText("独立页草稿")
        widget.showCompactPage()
        self.assertIs(widget.pageStack.currentWidget(), widget.compactPage)
        self.assertEqual(widget.inputEdit.toPlainText(), "独立页草稿")

        first_id = widget.conversationState.active_session_id
        widget.messages.append(ChatMessage("user", "第一段问题"))
        widget._persistConversations()
        widget.createConversation()
        second_id = widget.conversationState.active_session_id
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(widget.conversationState.sessions), 2)
        self.assertTrue(widget._switchConversation(0))
        self.assertEqual(widget.messages[0].content, "第一段问题")

        # Even if a late result arrives after an unexpected state change, its
        # immutable session ID keeps it out of the currently visible session.
        widget._onResult(_AIRequestOutcome(SimpleNamespace(
            text="第二段迟到回答", model="fixture", input_tokens=1, output_tokens=2,
        ), 0, second_id))
        first = next(one for one in widget.conversationState.sessions if one.id == first_id)
        second = next(one for one in widget.conversationState.sessions if one.id == second_id)
        self.assertNotIn("第二段迟到回答", [one.content for one in first.messages])
        self.assertIn("第二段迟到回答", [one.content for one in second.messages])

    def test_running_request_blocks_session_switch_and_creation(self):
        widget = self.create_interfaces()
        widget.createConversation()
        active_id = widget.conversationState.active_session_id
        widget.requestThread = SimpleNamespace(isRunning=lambda: True)
        with patch("app.AIInterface.InfoBar.warning") as warning:
            self.assertFalse(widget._switchConversation(0))
            widget.createConversation()
        self.assertEqual(widget.conversationState.active_session_id, active_id)
        self.assertEqual(len(widget.conversationState.sessions), 2)
        self.assertEqual(warning.call_count, 2)
        widget.requestThread = None

    def test_deferred_scroll_sync_is_safe_when_window_closes_immediately(self):
        widget = self.create_interfaces()
        widget.pageStack.setAnimationEnabled(False)
        widget.showExpandedConversation()
        widget.close()
        widget.deleteLater()
        app.sendPostedEvents(None, 0)
        app.processEvents()

    def test_missing_selected_cache_stops_before_provider_thread_is_created(self):
        widget = self.create_interfaces()
        widget.inputEdit.setPlainText("我的均分多少")
        context = SimpleNamespace(
            text="", counts={}, unavailable=("scores",),
        )
        with patch.object(widget, "saveConfiguration", return_value=True), \
             patch.object(widget, "_localCapabilityContext", return_value=context), \
             patch("app.AIInterface._AIRequestThread") as request_thread, \
             patch("app.AIInterface.InfoBar.warning"):
            widget._sendMessageFrom(widget.inputEdit)
        request_thread.assert_not_called()
        self.assertFalse(widget.messages)
        self.assertEqual(widget.inputEdit.toPlainText(), "我的均分多少")
        self.assertIn("成绩", widget.capabilityStatusLabel.text())

    def test_selected_empty_cache_context_starts_request_and_reaches_thread(self):
        widget = self.create_interfaces()
        widget.inputEdit.setPlainText("我的均分多少")
        context = SimpleNamespace(
            text=(
                "以下内容来自用户明确勾选的本机数据能力。\n\n"
                "## 我的成绩（已查询，0 条）\n- 本机缓存当前暂无记录；不得据此猜测。"
            ),
            counts=(("scores", 0),),
            unavailable=(),
        )
        with patch.object(widget, "saveConfiguration", return_value=True), \
             patch.object(widget, "_localCapabilityContext", return_value=context), \
             patch("app.AIInterface._AIRequestThread") as request_thread:
            widget._sendMessageFrom(widget.inputEdit)

        request_thread.assert_called_once()
        self.assertEqual(request_thread.call_args.kwargs["local_context"], context.text)
        request_thread.return_value.start.assert_called_once_with()
        self.assertEqual(widget.messages[-1].content, "我的均分多少")
        self.assertIn("我的成绩 0 条", widget.capabilityStatusLabel.text())

    def test_transcript_reacts_to_runtime_light_dark_theme_switch(self):
        widget = self.create_interfaces()
        widget.messages.append(ChatMessage("assistant", "```cpp\n#include <iostream>\n```"))
        widget.assistantMeta.append({})
        try:
            # qfluentwidgets keeps styled widgets in a WeakKeyDictionary.  Let
            # deferred deletions from earlier UI tests settle before it walks
            # that dictionary for a global theme change.
            app.sendPostedEvents(None, 0)
            gc.collect()
            setTheme(Theme.LIGHT)
            app.processEvents()
            light = widget.transcript.toHtml()
            setTheme(Theme.DARK)
            app.processEvents()
            dark = widget.transcript.toHtml()
            self.assertNotEqual(light, dark)
            self.assertIn("#272822", dark.lower())
            self.assertIn("#f6f8fa", light.lower())
            self.assertIn("iostream", widget.transcript.toPlainText())
        finally:
            setTheme(Theme.LIGHT)
            app.processEvents()

    def test_all_selected_cache_context_reaches_final_provider_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notice = root / "notification.json"
            notice.write_text(json.dumps([{
                "title": "通知边界夹具", "date": "2026-08-05", "source": "dean/jxtz",
            }]), encoding="utf-8")
            (root / "score.json").write_text(json.dumps({"scores": [{
                "courseName": "成绩边界夹具", "score": 92, "coursePoint": 3, "gpa": 4.1,
                "studentId": "never-send-this-id",
            }]}), encoding="utf-8")
            (root / "attendance_flow.json").write_text(json.dumps([{
                "sBh": "never-send-record-id", "eqno": "考勤边界教室",
                "watertime": "2026-08-05 09:00", "isdone": 1,
            }]), encoding="utf-8")
            connection = sqlite3.connect(root / "schedule.db")
            connection.execute(
                "CREATE TABLE courseinstance (name, day_of_week, start_time, end_time, week_number, location, teacher)"
            )
            connection.execute(
                "INSERT INTO courseinstance VALUES ('课表边界夹具', 1, 1, 2, 1, '教二楼', '教师')"
            )
            connection.commit()
            connection.close()
            context = collect_local_context(
                ("public_notices", "schedule", "scores", "attendance"),
                notification_path=notice,
                account_directory=root,
            )

            class CapturingClient:
                def __init__(self):
                    self.messages = None
                    self.session = SimpleNamespace(close=lambda: None)

                def complete(self, messages, _config):
                    self.messages = list(messages)
                    return SimpleNamespace(
                        text="ok", model="fixture", input_tokens=1, output_tokens=1
                    )

            thread = _AIRequestThread(
                [ChatMessage("system", "base"), ChatMessage("user", "查询")],
                ProviderConfig("openai", "https://api.example/v1", "fixture", "key"),
                local_context=context.text,
                session_id="session-boundary",
            )
            client = CapturingClient()
            thread.ai_client = client
            outcomes = []
            thread.succeeded.connect(outcomes.append)
            thread.run()
            self.assertEqual(outcomes[0].session_id, "session-boundary")
            self.assertEqual([one.role for one in client.messages], ["system", "system", "user"])
            sent = "\n".join(one.content for one in client.messages)
            for value in ("通知边界夹具", "课表边界夹具", "成绩边界夹具", "考勤边界教室"):
                self.assertIn(value, sent)
            self.assertNotIn("never-send-this-id", sent)
            self.assertNotIn("never-send-record-id", sent)

    def test_selected_empty_cache_status_reaches_final_provider_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "score.json").write_text(
                json.dumps({"scores": [], "terms": []}), encoding="utf-8"
            )
            context = collect_local_context(("scores",), account_directory=root)

            class CapturingClient:
                def __init__(self):
                    self.messages = None
                    self.session = SimpleNamespace(close=lambda: None)

                def complete(self, messages, _config):
                    self.messages = list(messages)
                    return SimpleNamespace(
                        text="ok", model="fixture", input_tokens=1, output_tokens=1
                    )

            thread = _AIRequestThread(
                [ChatMessage("system", "base"), ChatMessage("user", "我的均分多少")],
                ProviderConfig("openai", "https://api.example/v1", "fixture", "key"),
                local_context=context.text,
            )
            client = CapturingClient()
            thread.ai_client = client
            outcomes = []
            thread.succeeded.connect(outcomes.append)
            thread.run()

            self.assertTrue(outcomes)
            sent = "\n".join(one.content for one in client.messages)
            self.assertIn("我的成绩（已查询，0 条）", sent)
            self.assertIn("暂无记录", sent)
            self.assertIn("不得据此猜测", sent)

    def test_empty_message_does_not_start_request(self):
        widget = self.create_interfaces()
        with patch("app.AIInterface.InfoBar.warning"):
            widget.inputEdit.clear()
            widget.sendMessage()
        self.assertFalse(widget.messages)

    def test_legacy_smoke_setup_no_longer_references_qt5_embedded_webview(self):
        # The retained Qt 6 implementation is dormant source: importing the
        # normal Qt 5 application must not load or package its launcher.
        self.create_interfaces()
        self.assertNotIn("app.school_ai_browser", sys.modules)
        self.assertNotIn("app.school_ai_launcher", sys.modules)
        self.assertNotIn("PyQt6", sys.modules)

    def test_interfaces_construct_without_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            widget = AIInterface(config_store=AIConfigStore(
                Path(directory) / "profiles.json", keyring_backend=DummyKeyring()
            ))
            self.addCleanup(widget.close)
            widget.show()
            app.processEvents()
            self.assertEqual(widget.objectName(), "AIInterface")


if __name__ == "__main__":
    unittest.main()
