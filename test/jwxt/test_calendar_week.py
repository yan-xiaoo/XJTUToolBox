import unittest
from datetime import date
from unittest.mock import patch

from jwxt.calendar import CalendarTerm

TEST_DOMAIN = "schedule"


def _term(**overrides) -> CalendarTerm:
    data = {
        "term_id": "1",
        "start_date": "2024-02-26",
        "end_date": "2024-07-14",
        "term_num": "第二学期",
        "year_num": "2023-2024",
        "week_number": "20",
        "work_days": "5",
    }
    data.update(overrides)
    return CalendarTerm(**data)


class CalendarWeekTest(unittest.TestCase):
    def test_opening_week_boundaries_and_term_last_day(self):
        cases = (
            (date(2024, 2, 26), 1),
            (date(2024, 3, 3), 1),
            (date(2024, 3, 4), 2),
            (date(2024, 7, 14), 20),
        )
        for current, expected in cases:
            with self.subTest(current=current), patch("jwxt.calendar.date") as mock_date:
                mock_date.today.return_value = current
                self.assertEqual(_term().current_week, expected)

    def test_outside_term_has_no_current_week(self):
        term = _term()
        with patch("jwxt.calendar.date") as mock_date:
            mock_date.today.return_value = date(2025, 1, 1)
            self.assertIsNone(term.current_week)
        with patch("jwxt.calendar.date") as mock_date:
            mock_date.today.return_value = date(2024, 2, 1)
            self.assertIsNone(term.current_week)

    def test_inside_term_is_capped_by_week_number(self):
        term = _term()
        with patch("jwxt.calendar.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 4)
            self.assertEqual(term.current_week, 2)
        with patch("jwxt.calendar.date") as mock_date:
            mock_date.today.return_value = date(2024, 7, 14)
            self.assertEqual(term.current_week, 20)

    def test_invalid_dates_and_invalid_week_caps_return_none(self):
        terms = (
            _term(start_date="not-a-date"),
            _term(end_date="not-a-date"),
            _term(week_number=""),
            _term(week_number="invalid"),
            _term(week_number="0"),
            _term(week_number="-1"),
        )
        with patch("jwxt.calendar.date") as mock_date:
            mock_date.today.return_value = date(2024, 3, 4)
            for term in terms:
                with self.subTest(term=term):
                    self.assertIsNone(term.current_week)


if __name__ == "__main__":
    unittest.main()
