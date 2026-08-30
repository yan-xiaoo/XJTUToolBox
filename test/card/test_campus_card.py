import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_DOMAIN = "qt-ui"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from auth import ServerError
import card.campus_card as campus_card_module
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QWidget

CampusCard = campus_card_module.CampusCard
CardProfile = campus_card_module.CardProfile
TEST_PROFILE = CardProfile("Test User", "student-id", "card-id")


def _campus_card(session):
    return CampusCard(session, TEST_PROFILE)


def _response(payload=None, *, ok=True, error=None, text=""):
    response = SimpleNamespace(ok=ok, text=text)
    response.json = Mock(side_effect=error) if error else Mock(return_value=payload)
    return response


def _card_payload(code=200, *, cards=None, **card_overrides):
    card = {
        "elec_accamt": 123,
        "unsettle_amount": 45,
        "barflag": 1,
        "freezeflag": 0,
        "expdate": "20261231",
        "cardname": "校园卡",
    }
    card.update(card_overrides)
    return {
        "code": code,
        "data": {"card": [card] if cards is None else cards},
    }


def _transaction_item(amount=123, type_name="消费", icon="consume", **overrides):
    item = {
        "tranamt": amount,
        "turnoverType": type_name,
        "icon": icon,
        "toMerchant": "Synthetic Merchant",
        "cardBalance": 900,
        "jndatetimeStr": "2026-01-01 10:00:00",
        "resume": "Synthetic Merchant-transaction",
    }
    item.update(overrides)
    return item


def _transaction_payload(records, *, total=None, code=200):
    return {
        "code": code,
        "data": {
            "total": len(records) if total is None else total,
            "records": records,
        },
    }


class CampusCardApiTest(unittest.TestCase):
    def _card_session(self, response):
        return SimpleNamespace(
            get=Mock(return_value=response),
            user_name="Test User",
            student_no="student-id",
            card_account="card-id",
            headers={},
        )

    def test_card_info_accepts_string_success_code_and_uses_session_profile(self):
        session = self._card_session(_response(_card_payload("200")))

        info = _campus_card(session).get_card_info()

        self.assertEqual(info.name, "Test User")
        self.assertEqual(info.student_no, "student-id")
        self.assertEqual(info.account, "card-id")
        self.assertEqual(info.balance_cents, 123)
        self.assertEqual(info.pending_amount_cents, 45)
        self.assertIsInstance(info.balance_cents, int)
        self.assertIsInstance(info.pending_amount_cents, int)

    def test_card_info_rejects_invalid_response_shapes(self):
        cases = (
            _response(error=ValueError("broken")),
            _response(["not", "an", "object"]),
            _response({"data": {"card": []}}),
            _response({"code": 200, "data": []}),
            _response({"code": 200, "data": {"card": "not-a-list"}}),
            _response({"code": 500, "data": {"card": []}}),
            _response({"code": 200, "data": {"card": [{"elec_accamt": "1.5"}]}}),
            _response(_card_payload(), ok=False),
            _response(_card_payload(), text="请浏览器调成移动端模式访问！"),
        )
        for response in cases:
            with self.subTest(response=response):
                with self.assertRaisesRegex(ServerError, "查询校园卡"):
                    _campus_card(self._card_session(response)).get_card_info()

    def test_transaction_code_is_checked(self):
        session = SimpleNamespace(get=Mock(return_value=_response({"code": 500, "message": "查询失败"})))
        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(session).get_transactions(date(2026, 1, 1), date(2026, 1, 2))

    def test_profile_is_required_at_construction(self):
        with self.assertRaises(TypeError):
            CampusCard(SimpleNamespace(get=Mock()), object())

        with self.assertRaises(ValueError):
            CardProfile("", "student-id", "card-id")

    def test_transactions_reject_invalid_response_shapes(self):
        cases = (
            _response(error=ValueError("broken")),
            _response(["not", "an", "object"]),
            _response({"data": {"total": 0, "records": []}}),
            _response({"code": 500, "data": {"total": 0, "records": []}}),
            _response({"code": 200, "data": []}),
            _response({"code": 200, "data": {"total": 1, "records": "not-a-list"}}),
            _response({"code": 200, "data": {"total": "bad", "records": []}}),
            _response(_transaction_payload([{"tranamt": "bad"}])),
        )
        for response in cases:
            with self.subTest(response=response):
                session = SimpleNamespace(get=Mock(return_value=response))
                with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
                    _campus_card(session).get_transactions(date(2026, 1, 1), date(2026, 1, 2))

    def test_transaction_amounts_are_integer_cents_with_explicit_direction(self):
        cases = (
            ("消费", "consume", 123, -123),
            ("充值", "recharge", 123, 123),
            ("圈存", "transfer-in", 123, 123),
            ("退款", "refund", 123, 123),
            ("补助", "subsidy", 123, 123),
            ("未知类型", "unknown", 123, 123),
            ("未知类型", "unknown", -123, -123),
            ("转出", "transfer-out", 123, -123),
            ("未知类型", "transfer", 123, 123),
        )
        records = [
            _transaction_item(amount=amount, type_name=type_name, icon=icon)
            for type_name, icon, amount, _expected in cases
        ]
        session = SimpleNamespace(get=Mock(return_value=_response(_transaction_payload(records))))

        _total, transactions = _campus_card(session).get_transactions()

        for transaction, (_type_name, _icon, _amount, expected) in zip(transactions, cases):
            self.assertEqual(transaction.amount_cents, expected)
            self.assertIsInstance(transaction.amount_cents, int)
            self.assertIsInstance(transaction.balance_cents, int)

        signed_amount_cents = getattr(campus_card_module, "_signed_amount_cents", None)
        self.assertIsNotNone(signed_amount_cents)
        self.assertEqual(
            [signed_amount_cents(amount, type_name, icon) for type_name, icon, amount, _ in cases],
            [expected for _type_name, _icon, _amount, expected in cases],
        )

    def test_get_all_transactions_pages_until_total(self):
        pages = {
            1: _transaction_payload([
                _transaction_item(jndatetimeStr="1"),
                _transaction_item(jndatetimeStr="2"),
            ], total=3),
            2: _transaction_payload([_transaction_item(jndatetimeStr="3")], total=3),
        }

        def fake_get(url, params=None, timeout=20):
            payload = pages[params["current"]]
            return _response(payload)

        session = SimpleNamespace(get=fake_get)
        total, records = _campus_card(session).get_all_transactions(
            date(2026, 1, 1), date(2026, 3, 1), page_size=2,
        )
        self.assertEqual(total, 3)
        self.assertEqual(len(records), 3)

    def test_get_all_transactions_rejects_early_empty_page_with_bound(self):
        requested_pages = []

        def fake_get(url, params=None, timeout=20):
            requested_pages.append(params["current"])
            if params["current"] == 1:
                return _response(_transaction_payload([_transaction_item(jndatetimeStr="1")], total=3))
            return _response(_transaction_payload([], total=3))

        session = SimpleNamespace(get=fake_get)
        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(session).get_all_transactions(page_size=2)
        self.assertEqual(requested_pages, [1, 2])

    def test_get_all_transactions_rejects_short_result_after_final_page(self):
        requested_pages = []
        pages = {
            1: _transaction_payload([_transaction_item(jndatetimeStr="1")], total=5),
            2: _transaction_payload([_transaction_item(jndatetimeStr="2")], total=5),
            3: _transaction_payload([_transaction_item(jndatetimeStr="3")], total=5),
        }

        def fake_get(url, params=None, timeout=20):
            requested_pages.append(params["current"])
            return _response(pages[params["current"]])

        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(SimpleNamespace(get=fake_get)).get_all_transactions(page_size=2)
        self.assertEqual(requested_pages, [1, 2, 3])

    def test_get_all_transactions_rejects_total_changes(self):
        requested_pages = []
        pages = {
            1: _transaction_payload([_transaction_item(jndatetimeStr="1")], total=2),
            2: _transaction_payload([_transaction_item(jndatetimeStr="2")], total=3),
        }

        def fake_get(url, params=None, timeout=20):
            requested_pages.append(params["current"])
            return _response(pages[params["current"]])

        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(SimpleNamespace(get=fake_get)).get_all_transactions(page_size=1)
        self.assertEqual(requested_pages, [1, 2])

    def test_get_all_transactions_rejects_repeated_page_without_unbounded_requests(self):
        requested_pages = []
        page = _transaction_payload([_transaction_item(jndatetimeStr="same")], total=4)

        def fake_get(url, params=None, timeout=20):
            requested_pages.append(params["current"])
            if len(requested_pages) > 4:
                raise AssertionError("pagination exceeded the page bound")
            return _response(page)

        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(SimpleNamespace(get=fake_get)).get_all_transactions(page_size=1)
        self.assertEqual(requested_pages, [1, 2])

    def test_get_all_transactions_rejects_non_positive_page_size_before_request(self):
        session = SimpleNamespace(get=Mock())
        with self.assertRaisesRegex(ServerError, "查询校园卡流水"):
            _campus_card(session).get_all_transactions(page_size=0)
        session.get.assert_not_called()


class CampusCardAccountSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_account_change_clears_page(self):
        from app.CampusCardInterface import CampusCardInterface

        page = CampusCardInterface()
        page.table.setRowCount(2)
        page._auto_loaded = True
        page.on_account_changed()
        self.assertFalse(page._auto_loaded)
        self.assertEqual(page.table.rowCount(), 0)

    def _page_with_accounts(self):
        from app.CampusCardInterface import CampusCardInterface
        from app.utils.account import AccountManager

        first = SimpleNamespace(uuid="first", username="first")
        second = SimpleNamespace(uuid="second", username="second")
        manager = AccountManager(first, second)
        patches = (
            patch("app.CampusCardInterface.accounts", manager),
            patch("app.components.CampusPage.accounts", manager),
        )
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        page = CampusCardInterface()
        self.addCleanup(page.deleteLater)
        return page, manager, first, second

    def test_real_account_changed_signal_clears_summary_and_table(self):
        page, manager, _first, second = self._page_with_accounts()
        page._auto_loaded = True
        page.summary.setText("旧账户摘要")
        page.table.setRowCount(1)

        manager.current = second

        self.assertFalse(page._auto_loaded)
        self.assertIn("自动查询", page.summary.text())
        self.assertEqual(page.table.rowCount(), 0)

    def test_reverse_date_range_does_not_start_background_job(self):
        page, _manager, _first, _second = self._page_with_accounts()
        page.fromPicker.setDate(QDate(2026, 3, 2))
        page.toPicker.setDate(QDate(2026, 3, 1))

        with patch.object(page, "start_job") as start, patch.object(page, "warn") as warn:
            page.refresh()

        start.assert_not_called()
        warn.assert_called_once()
        self.assertIn("开始日期", warn.call_args.args[1])

    def test_switching_account_discards_old_result_and_error_from_card_page(self):
        from app.components.CampusPage import CampusPage

        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

            def emit(self, *args):
                for callback in tuple(self.callbacks):
                    callback(*args)

        class FakeThread:
            def __init__(self, *args, **kwargs):
                self.can_run = True
                self.result = FakeSignal()
                self.error = FakeSignal()
                self.running = True

            def isRunning(self):
                return self.running

            def start(self):
                pass

        page, manager, _first, second = self._page_with_accounts()
        on_result = Mock()
        with patch("app.components.CampusPage.CampusFeatureThread", FakeThread), \
             patch("app.components.CampusPage.ProcessWidget", side_effect=lambda *args, **kwargs: QWidget()), \
             patch.object(page, "warn") as warn:
            page.start_job("campus_card", "查询", Mock(), on_result, show_process=False)
            old_thread = page.thread
            manager.current = second
            old_thread.result.emit("旧结果")
            old_thread.error.emit("旧错误", "旧消息")

        on_result.assert_not_called()
        warn.assert_not_called()

    def test_second_refresh_wins_over_earlier_result_and_error(self):
        from app.components.CampusPage import CampusPage

        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

            def emit(self, *args):
                for callback in tuple(self.callbacks):
                    callback(*args)

        class FakeThread:
            created = []

            def __init__(self, *args, **kwargs):
                self.can_run = True
                self.result = FakeSignal()
                self.error = FakeSignal()
                self.running = True
                self.created.append(self)

            def isRunning(self):
                return self.running

            def start(self):
                pass

        page, _manager, _first, _second = self._page_with_accounts()
        on_result = Mock()
        with patch("app.components.CampusPage.CampusFeatureThread", FakeThread), \
             patch("app.components.CampusPage.ProcessWidget", return_value=None), \
             patch.object(page, "warn") as warn:
            CampusPage.start_job(page, "campus_card", "查询", Mock(), on_result, show_process=False)
            CampusPage.start_job(page, "campus_card", "查询", Mock(), on_result, show_process=False)
            first_thread, second_thread = FakeThread.created[-2:]
            first_thread.result.emit("旧结果")
            first_thread.error.emit("旧错误", "旧消息")
            second_thread.result.emit("新结果")

        on_result.assert_called_once_with("新结果")
        warn.assert_not_called()

    def test_current_query_error_preserves_last_successful_view(self):
        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

            def emit(self, *args):
                for callback in tuple(self.callbacks):
                    callback(*args)

        class FakeThread:
            def __init__(self, *args, **kwargs):
                self.can_run = True
                self.result = FakeSignal()
                self.error = FakeSignal()
                self.running = True

            def isRunning(self):
                return self.running

            def start(self):
                pass

        page, _manager, _first, _second = self._page_with_accounts()
        page.summary.setText("上一次成功结果")
        page.table.setRowCount(1)
        page.fromPicker.setDate(QDate(2026, 1, 1))
        page.toPicker.setDate(QDate(2026, 1, 31))
        with patch("app.components.CampusPage.CampusFeatureThread", FakeThread), \
             patch("app.components.CampusPage.ProcessWidget", side_effect=lambda *args, **kwargs: QWidget()), \
             patch.object(page, "warn") as warn:
            page.refresh()
            page.thread.error.emit("查询失败", "服务暂时不可用")

        self.assertEqual(page.summary.text(), "上一次成功结果")
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.fromPicker.getDate(), QDate(2026, 1, 1))
        self.assertEqual(page.toPicker.getDate(), QDate(2026, 1, 31))
        warn.assert_called_once_with("查询失败", "服务暂时不可用")


if __name__ == "__main__":
    unittest.main()
