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

    def test_json_rejects_non_object(self):
        with self.assertRaises(ServerError):
            _json(SimpleNamespace(json=lambda: ["not", "an", "object"]))


if __name__ == "__main__":
    unittest.main()
