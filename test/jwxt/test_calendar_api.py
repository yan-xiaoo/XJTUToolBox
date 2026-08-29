import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from auth import ServerError
from jwxt.calendar import SchoolCalendar

TEST_DOMAIN = "schedule"


def _response(payload=None, *, error=None):
    return SimpleNamespace(
        json=Mock(side_effect=error) if error else Mock(return_value=payload),
    )


def _term(**overrides):
    item = {
        "id": 2,
        "start_date": "2024-02-26 00:00:00",
        "end_date": "2024-07-14 00:00:00",
        "term_num": "2",
        "year_num": "2023-2024",
        "week_number": 20,
        "work_days": 5,
        "holidays": [{
            "holiday_name": "劳动节",
            "start_date": "2024-05-01",
            "end_date": "2024-05-05",
            "holiday_days": 5,
            "holiday_remark": "调休",
        }],
    }
    item.update(overrides)
    return item


class SchoolCalendarApiTest(unittest.TestCase):
    def test_warmup_failure_does_not_block_post_and_ajax_headers_are_exact(self):
        session = SimpleNamespace(
            get=Mock(side_effect=requests.ConnectionError("warmup")),
            post=Mock(return_value=_response({"code": 200, "data": []})),
        )
        self.assertEqual(SchoolCalendar(session).get_terms(), [])
        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["headers"], {
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "http://one2020.xjtu.edu.cn",
            "Referer": SchoolCalendar.SHOW_URL,
        })

    def test_api_error_malformed_json_non_object_and_empty_terms(self):
        cases = (
            (_response({"code": 500, "msg": "denied"}), ServerError),
            (_response(error=ValueError("broken")), ServerError),
            (_response(["not", "object"]), ServerError),
            (_response({"code": 200, "data": []}), None),
        )
        for response, error_type in cases:
            with self.subTest(response=response):
                session = SimpleNamespace(get=Mock(), post=Mock(return_value=response))
                if error_type:
                    with self.assertRaises(error_type):
                        SchoolCalendar(session).get_terms()
                else:
                    self.assertEqual(SchoolCalendar(session).get_terms(), [])

    def test_wrong_typed_data_terms_holidays_and_holiday_items_are_rejected(self):
        payloads = (
            {"code": 200, "data": {}},
            {"code": 200, "data": ["not-object"]},
            {"code": 200, "data": [_term(holidays={})]},
            {"code": 200, "data": [_term(holidays=["not-object"])]},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                session = SimpleNamespace(get=Mock(), post=Mock(return_value=_response(payload)))
                with self.assertRaises(ServerError):
                    SchoolCalendar(session).get_terms()

    def test_complete_term_and_holiday_fields_map(self):
        session = SimpleNamespace(
            get=Mock(), post=Mock(return_value=_response({"code": 200, "data": [_term()]})),
        )
        term = SchoolCalendar(session).get_terms()[0]
        self.assertEqual((term.term_id, term.start_date, term.end_date),
                         ("2", "2024-02-26 00:00:00", "2024-07-14 00:00:00"))
        self.assertEqual((term.term_num, term.year_num, term.week_number, term.work_days),
                         ("2", "2023-2024", "20", "5"))
        holiday = term.holidays[0]
        self.assertEqual((holiday.name, holiday.start_date, holiday.end_date, holiday.days, holiday.remark),
                         ("劳动节", "2024-05-01", "2024-05-05", "5", "调休"))

    def test_missing_optional_holiday_fields_are_empty(self):
        session = SimpleNamespace(
            get=Mock(), post=Mock(return_value=_response({
                "code": 200, "data": [_term(holidays=[{}])],
            })),
        )
        holiday = SchoolCalendar(session).get_terms()[0].holidays[0]
        self.assertEqual((holiday.name, holiday.start_date, holiday.end_date, holiday.days, holiday.remark),
                         ("", "", "", "", ""))

    def test_multiple_terms_have_stable_newest_first_order(self):
        older = _term(id=1, start_date="2023-09-01", year_num="2023-2024", term_num="1")
        newer = _term(id=3, start_date="2024-09-01", year_num="2024-2025", term_num="1")
        middle = _term(id=2, start_date="2024-02-26", year_num="2023-2024", term_num="2")
        session = SimpleNamespace(
            get=Mock(), post=Mock(return_value=_response({"code": 200, "data": [older, newer, middle]})),
        )
        self.assertEqual([item.term_id for item in SchoolCalendar(session).get_terms()], ["3", "2", "1"])


if __name__ == "__main__":
    unittest.main()
