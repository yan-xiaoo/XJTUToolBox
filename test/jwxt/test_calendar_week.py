import unittest
from datetime import date
from unittest.mock import patch

from jwxt.calendar import CalendarTerm


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


if __name__ == "__main__":
    unittest.main()
