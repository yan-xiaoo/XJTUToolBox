import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auth import ServerError
from fitness.score import Fitness


def _response(payload):
    return SimpleNamespace(json=Mock(return_value=payload))


def _session(payload, *, referer=None, header_referer=None):
    headers = {}
    if header_referer is not None:
        headers["X-Fitness-Referer"] = header_referer
    session = SimpleNamespace(headers=headers, post=Mock(return_value=_response(payload)))
    if referer is not None:
        session.referer_url = referer
    return session


class FitnessYearsTest(unittest.TestCase):
    def test_referer_attribute_has_priority_over_header_and_default(self):
        session = _session({"status": 1, "data": {"list": []}},
                           referer="attribute", header_referer="header")
        Fitness(session).get_years()
        self.assertEqual(session.post.call_args.kwargs["headers"]["Referer"], "attribute")

        session = _session({"status": 1, "data": {"list": []}}, header_referer="header")
        Fitness(session).get_years()
        self.assertEqual(session.post.call_args.kwargs["headers"]["Referer"], "header")

        session = _session({"status": 1, "data": {"list": []}})
        Fitness(session).get_years()
        self.assertEqual(
            session.post.call_args.kwargs["headers"]["Referer"],
            "https://tyxylp.xjtu.edu.cn/bdlp_h5_fitness_test/view/h5xajt/#/pages/index/index",
        )

    def test_september_boundary_and_future_numeric_filter(self):
        payload = {"status": 1, "data": {"list": [
            {"year_num": "2023", "name": "2023-2024", "checked": False},
            {"year_num": "2024", "name": "2024-2025", "checked": True},
            {"year_num": "2025", "name": "future", "checked": False},
        ]}}
        with patch("fitness.score.date") as today:
            today.today.return_value = date(2024, 8, 31)
            years = Fitness(_session(payload)).get_years()
            self.assertEqual([item.year_num for item in years], ["2023"])
        with patch("fitness.score.date") as today:
            today.today.return_value = date(2024, 9, 1)
            years = Fitness(_session(payload)).get_years()
            self.assertEqual([item.year_num for item in years], ["2023", "2024"])

    def test_non_numeric_year_is_preserved(self):
        payload = {"status": 1, "data": {"list": [
            {"year_num": "unknown", "name": "unknown", "checked": False},
            {"year_num": "2026", "name": "future", "checked": False},
        ]}}
        with patch("fitness.score.date") as today:
            today.today.return_value = date(2024, 1, 1)
            years = Fitness(_session(payload)).get_years()
        self.assertEqual([item.year_num for item in years], ["unknown"])

    def test_empty_and_missing_year_list_are_empty(self):
        for payload in (
            {"status": 1, "data": {"list": []}},
            {"status": 1, "data": {}},
            {"status": 1},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(Fitness(_session(payload)).get_years(), [])

    def test_wrong_typed_year_data_and_items_are_rejected(self):
        payloads = (
            {"status": 1, "data": []},
            {"status": 1, "data": {"list": "not-list"}},
            {"status": 1, "data": {"list": ["not-object"]}},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ServerError):
                    Fitness(_session(payload)).get_years()

    def test_api_business_failure_is_server_error(self):
        with self.assertRaises(ServerError) as caught:
            Fitness(_session({"status": 0, "info": "denied"})).get_years()
        self.assertEqual(caught.exception.message, "denied")


if __name__ == "__main__":
    unittest.main()
