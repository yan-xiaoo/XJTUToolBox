import unittest
from unittest.mock import Mock

from qms.judge import QMSAutoJudge, QMSQuestionnaire


class _FakeResponse:
    status_code = 204
    content = b""
    headers = {}
    text = ""

    def json(self):
        return {}


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.response = _FakeResponse()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class QMSAnswerBuilderTest(unittest.TestCase):
    def setUp(self):
        self.detail = {
            "response": {"id": "response-1", "answers": [], "status": "DRAFT"},
            "labelSurvey": [
                {
                    "survey": {
                        "id": "survey-1",
                        "questions": [
                            {
                                "id": "q-scoring",
                                "type": "SCORING",
                                "options": {"min_range": 1, "max_range": 20, "decimal_places": 0},
                                "sub_questions": [],
                            },
                            {
                                "id": "q-matrix",
                                "type": "MATRIX",
                                "choices": [
                                    {"id": "best", "options": {"score": 1}},
                                    {"id": "good", "options": {"score": 2}},
                                    {"id": "bad", "options": {"score": 3}},
                                ],
                                "sub_questions": [{"id": "sub-1"}, {"id": "sub-2"}],
                            },
                            {
                                "id": "q-text",
                                "type": "SHORT_ANSWER",
                                "options": {"input_min_length": 10},
                            },
                        ],
                    }
                }
            ],
        }

    def test_percent_mapping(self):
        judge = QMSAutoJudge(session=None)
        self.assertEqual(judge._choice_index([{}, {}, {}, {}, {}], 100), 0)
        self.assertEqual(judge._choice_index([{}, {}, {}, {}, {}], 60), 2)

    def test_build_answers(self):
        judge = QMSAutoJudge(session=None)
        surveys = judge.build_more_survey_answers(self.detail, 100, "很好")
        self.assertEqual(len(surveys), 1)
        self.assertEqual(surveys[0]["survey_id"], "survey-1")
        answers = surveys[0]["answers"]
        self.assertEqual(len(answers), 3)
        self.assertEqual(answers[0]["score"], 20)
        self.assertEqual(answers[1]["answer"][0]["answer"], "best")
        self.assertEqual(answers[1]["score"], 2)
        self.assertGreaterEqual(len(answers[2]["answer"]), 10)
        self.assertEqual(answers[2]["preset_replies"], [])

    def test_submit_payload_uses_qms_snake_case(self):
        session = _FakeSession()
        judge = QMSAutoJudge(session)
        judge._get_response_detail = Mock(return_value=self.detail)
        questionnaire = QMSQuestionnaire(
            task_id=1,
            plan_instance_id=2,
            plan_title="评教",
            course_id=3,
            course_name="课程",
            course_code="CODE",
            teaching_class_code="CLASS",
            open_department="学院",
            lecturers=["教师"],
            response_id="response-1",
            status="DRAFT",
            task={},
            course={},
            response={},
        )
        ok, msg = judge.save_answers(questionnaire, 100, "很好", submit=True)
        self.assertTrue(ok, msg)
        method, url, kwargs = session.calls[0]
        payload = kwargs["json"]
        self.assertEqual(method, "PUT")
        self.assertIn("/api/quality/more-survey/responses/response-1", url)
        self.assertEqual(payload["status"], "ENABLED")
        self.assertIn("extension_data", payload)
        self.assertIn("more_survey_answers", payload)
        self.assertNotIn("moreSurveyAnswers", payload)


if __name__ == "__main__":
    unittest.main()
