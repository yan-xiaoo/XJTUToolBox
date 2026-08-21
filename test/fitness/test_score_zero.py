import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from auth import ServerError
from fitness.score import Fitness, _json


class FitnessScoreZeroTest(unittest.TestCase):
    def test_zero_scores_are_kept(self):
        session = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
            json=lambda: {
                "status": 1,
                "data": {
                    "bmi_score_new": 0,
                    "bmi_score": 99,
                    "total_score": 0,
                    "student_name": "张三",
                    "student_num": "1",
                },
            }
        )))
        score = Fitness(session).get_score("2024")
        self.assertEqual(score.total_score, "0")
        bmi = next(item for item in score.items if item.key == "bmi")
        self.assertEqual(bmi.score, "0")

    def test_total_and_all_seven_items_map_complete_fields(self):
        data = {
            "student_num": 1, "student_name": "张三", "total_score": 91,
            "total_grade": "优秀", "report_type": "final", "report_status": "done",
            "sex": 1, "grade": 2024,
        }
        for index, key in enumerate(("bmi", "vc", "jump", "sit_and_reach", "pull_and_sit", "50m", "run"), 1):
            data.update({f"{key}_score": index, f"{key}_grade": f"G{index}", f"{key}_class": f"C{index}"})
        session = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
            json=lambda: {"status": 1, "data": data}
        )))
        score = Fitness(session).get_score("2024")
        self.assertEqual(score.student_num, "1")
        self.assertEqual(score.total_grade, "优秀")
        self.assertEqual(len(score.items), 7)
        for index, item in enumerate(score.items, 1):
            self.assertEqual(item.score, str(index))
            self.assertEqual(item.grade, f"G{index}")
            self.assertEqual(item.extra, f"C{index}")

    def test_new_bmi_zero_wins_and_none_or_missing_falls_back(self):
        def score(data):
            session = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
                json=lambda: {"status": 1, "data": data}
            )))
            return next(item for item in Fitness(session).get_score("2024").items if item.key == "bmi").score

        self.assertEqual(score({"bmi_score_new": 0, "bmi_score": 88}), "0")
        self.assertEqual(score({"bmi_score_new": None, "bmi_score": 88}), "88")
        self.assertEqual(score({"bmi_score": 88}), "88")

    def test_missing_scores_are_empty_and_partial_items_render(self):
        session = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
            json=lambda: {"status": 1, "data": {"vc_score": 0, "vc_grade": "合格"}}
        )))
        score = Fitness(session).get_score("2024")
        vc = next(item for item in score.items if item.key == "vc")
        bmi = next(item for item in score.items if item.key == "bmi")
        self.assertEqual((vc.score, vc.grade, vc.extra), ("0", "合格", ""))
        self.assertEqual((bmi.score, bmi.grade, bmi.extra), ("", "", ""))

    def test_wrong_top_level_and_data_shapes_are_rejected(self):
        for payload in (["not"], "string", None, {"status": 1, "data": []}, {"status": 1, "data": "bad"}):
            with self.subTest(payload=payload):
                session = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(json=lambda: payload)))
                with self.assertRaises(ServerError):
                    Fitness(session).get_score("2024")

    def test_broken_json_and_business_failure_are_rejected(self):
        broken = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
            json=Mock(side_effect=ValueError("broken"))
        )))
        failed = SimpleNamespace(headers={}, post=Mock(return_value=SimpleNamespace(
            json=lambda: {"status": 0, "info": "denied"}
        )))
        with self.assertRaises(ServerError):
            Fitness(broken).get_score("2024")
        with self.assertRaises(ServerError) as caught:
            Fitness(failed).get_score("2024")
        self.assertEqual(caught.exception.message, "denied")

    def test_json_rejects_non_object(self):
        with self.assertRaises(ServerError):
            _json(SimpleNamespace(json=lambda: ["not", "an", "object"]))


if __name__ == "__main__":
    unittest.main()
