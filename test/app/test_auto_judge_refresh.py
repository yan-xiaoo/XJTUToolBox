import importlib
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.threads.JudgeThread import JudgeChoice, JudgeThread

auto_judge = importlib.import_module("app.sub_interfaces.AutoJudgeInterface")

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
APP = QApplication.instance() or QApplication([])


class ControlledJudgeThread(JudgeThread):
    """Keep each run alive until the test allows its native finished signal."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.submit_release = threading.Event()
        self.refresh_release = threading.Event()
        self.refresh_entered = threading.Event()
        self.start_calls = []
        self.refresh_result = None

    def start(self):
        self.start_calls.append((self.choice, self.isRunning()))
        super().start()

    def run(self):
        if self.choice == JudgeChoice.JUDGE_ALL:
            self.submitSuccess.emit()
            self.hasFinished.emit()
            self.submit_release.wait(5)
        elif self.choice == JudgeChoice.GET_COURSES:
            self.refresh_entered.set()
            self.refresh_release.wait(5)
            if self.refresh_result is None:
                self.error.emit("刷新失败", "模拟网络错误")
                self.canceled.emit()
            else:
                self.questionnaires.emit(*self.refresh_result)
                self.hasFinished.emit()


def questionnaire(name):
    return SimpleNamespace(display_title=name, display_description="测试问卷")


class AutoJudgeRefreshTest(unittest.TestCase):
    def setUp(self):
        self.accounts = SimpleNamespace(current=object(), currentAccountChanged=Mock())
        for name, value in (
            ("accounts", self.accounts),
            ("JudgeThread", ControlledJudgeThread),
            ("InfoBar", Mock()),
        ):
            patcher = patch.object(auto_judge, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.widget = auto_judge.AutoJudgeInterface()
        self.thread = self.widget.thread_
        self.addCleanup(self.cleanup_widget)
        self.old_pending = questionnaire("待评教课程")
        self.old_finished = questionnaire("已评教课程")
        self.widget.onGetQuestionnaireFinish([self.old_pending], [self.old_finished])
        self.old_cards = self.cards()

    def cleanup_widget(self):
        self.thread.submitSuccess.disconnect(self.widget.onSubmitSuccess)
        self.thread.finished.disconnect(self.widget.onThreadFinished)
        self.thread.submit_release.set()
        self.thread.refresh_release.set()
        self.assertTrue(self.thread.wait(5000))
        APP.processEvents()
        self.widget.processWidget.timer.stop()
        self.widget.close()
        self.widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def cards(self):
        return self.widget.questionnaireWidgets + self.widget.finishedQuestionnaireWidgets

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(1)
        self.assertTrue(predicate(), "Timed out waiting for Qt events")

    def finish_refresh(self):
        self.thread.refresh_release.set()
        self.assertTrue(self.thread.wait(5000))
        APP.processEvents()

    def test_batch_refresh_waits_for_native_finished(self):
        self.thread.choice = JudgeChoice.JUDGE_ALL
        self.thread.start()
        self.wait_until(lambda: self.widget._refresh_after_finished)
        QTest.qWait(10)  # Give a zero-delay timer the opportunity to fire.

        self.assertTrue(self.thread.isRunning())
        self.assertEqual(self.thread.start_calls, [(JudgeChoice.JUDGE_ALL, False)])
        self.assertEqual(self.cards(), self.old_cards)
        self.widget.onStartButtonClicked()
        self.assertEqual(self.thread.choice, JudgeChoice.JUDGE_ALL)
        self.assertEqual(len(self.thread.start_calls), 1)

        self.thread.submit_release.set()
        self.wait_until(self.thread.refresh_entered.is_set)
        self.wait_until(self.widget.processWidget.timer.isActive)
        self.assertEqual(self.thread.start_calls, [
            (JudgeChoice.JUDGE_ALL, False), (JudgeChoice.GET_COURSES, False)
        ])
        self.assertFalse(self.widget._refresh_after_finished)
        self.assertFalse(self.widget.processWidget.isHidden())
        self.assertEqual(self.cards(), self.old_cards)
        self.assertTrue(all(not card.submitButton.isEnabled() for card in self.cards()))
        self.finish_refresh()
        self.assertFalse(self.widget.processWidget.timer.isActive())

    def test_failed_refresh_keeps_existing_cards_and_unlocks_them(self):
        self.widget.onStartButtonClicked()
        self.wait_until(self.thread.refresh_entered.is_set)
        self.assertEqual(self.cards(), self.old_cards)
        self.assertTrue(all(not card.submitButton.isEnabled() for card in self.cards()))

        self.finish_refresh()

        self.assertEqual(self.cards(), self.old_cards)
        self.assertIs(self.widget.currentFrame, self.widget.questionnaireFrame)
        self.assertTrue(all(card.submitButton.isEnabled() for card in self.cards()))
        auto_judge.InfoBar.error.assert_called_once()

    def test_successful_refresh_replaces_both_lists(self):
        pending, finished = questionnaire("新课程"), questionnaire("新已评课程")
        self.thread.refresh_result = ([pending], [finished])
        self.widget.onStartButtonClicked()
        self.wait_until(self.thread.refresh_entered.is_set)
        self.assertEqual(self.cards(), self.old_cards)

        self.finish_refresh()

        self.assertEqual([card.questionnaire for card in self.widget.questionnaireWidgets], [pending])
        self.assertEqual([card.questionnaire for card in self.widget.finishedQuestionnaireWidgets], [finished])
        self.assertTrue(all(card.submitButton.isEnabled() for card in self.cards()))

    def test_account_change_cancels_pending_batch_refresh(self):
        self.thread.choice = JudgeChoice.JUDGE_ALL
        self.thread.start()
        self.wait_until(lambda: self.widget._refresh_after_finished)

        self.accounts.current = None
        self.widget.onCurrentAccountChanged()
        self.thread.submit_release.set()
        self.assertTrue(self.thread.wait(5000))
        APP.processEvents()

        self.assertEqual(self.thread.start_calls, [(JudgeChoice.JUDGE_ALL, False)])
        self.assertFalse(self.widget._refresh_after_finished)
        self.assertIs(self.widget.currentFrame, self.widget.startFrame)


if __name__ == "__main__":
    unittest.main()
