import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from auth import ServerError
from card.campus_card import CampusCard


class CampusCardApiTest(unittest.TestCase):
    def test_transaction_code_is_checked(self):
        session = SimpleNamespace(get=Mock(return_value=SimpleNamespace(
            text="",
            json=lambda: {"code": 500, "message": "查询失败"},
        )))
        with self.assertRaises(ServerError) as ctx:
            CampusCard(session).get_transactions(date(2026, 1, 1), date(2026, 1, 2))
        self.assertIn("查询失败", str(ctx.exception))

    def test_get_all_transactions_pages_until_total(self):
        pages = {
            1: {"code": 200, "data": {"total": 3, "records": [
                {"tranamt": 100, "turnoverType": "消费", "toMerchant": "食堂", "cardBalance": 900, "jndatetimeStr": "1"},
                {"tranamt": 100, "turnoverType": "消费", "toMerchant": "食堂", "cardBalance": 800, "jndatetimeStr": "2"},
            ]}},
            2: {"code": 200, "data": {"total": 3, "records": [
                {"tranamt": 100, "turnoverType": "消费", "toMerchant": "食堂", "cardBalance": 700, "jndatetimeStr": "3"},
            ]}},
        }

        def fake_get(url, params=None, timeout=20):
            payload = pages[params["current"]]
            return SimpleNamespace(text="", json=lambda payload=payload: payload)

        session = SimpleNamespace(get=fake_get)
        total, records = CampusCard(session).get_all_transactions(
            date(2026, 1, 1), date(2026, 3, 1), page_size=2,
        )
        self.assertEqual(total, 3)
        self.assertEqual(len(records), 3)


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


if __name__ == "__main__":
    unittest.main()
