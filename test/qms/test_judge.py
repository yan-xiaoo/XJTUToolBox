import unittest
from unittest.mock import Mock

TEST_DOMAIN = "auth-session"
TEST_REGRESSION = True

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


class QMSQuestionnaireDisplayTest(unittest.TestCase):
    def questionnaires(self, responses, status="DRAFT"):
        course = {
            "course_id": 3,
            "primary_plan_course_name": "测试课程",
            "lecturers": ["教师甲", "教师乙"],
            "surveys": [{"response": response} for response in responses],
        }
        judge = QMSAutoJudge(session=None)
        judge._request = Mock(side_effect=[
            {"data": [{"id": 1, "plan_instance": {
                "id": 2, "plan": {"business_code": "student-evaluation"},
            }}]},
            {"data": [course] if status == "DRAFT" else []},
            {"data": [course] if status == "ENABLED" else []},
        ])
        return judge.get_questionnaires()

    def test_each_response_displays_its_own_teacher(self):
        for status in ("DRAFT", "ENABLED"):
            with self.subTest(status=status):
                responses = [
                    {"id": "response-b", "status": status, "target": {
                        "attributes": {"course": {"lecturers": [{"name": "教师乙"}]}},
                    }},
                    {"id": "response-a", "status": status, "target": {
                        "attributes": {"course": {"lecturers": [{"name": "教师甲"}]}},
                    }},
                ]
                pending, finished = self.questionnaires(responses, status)
                items = pending if status == "DRAFT" else finished
                self.assertEqual(len(items), 2)
                self.assertEqual(finished if status == "DRAFT" else pending, [])
                self.assertEqual(
                    {item.BPR: item.display_title for item in items},
                    {"response-a": "测试课程 教师甲", "response-b": "测试课程 教师乙"},
                )
                for item in items:
                    self.assertEqual(item.JSXM, item.BPJS)
                    self.assertEqual(item.lecturers, ["教师甲", "教师乙"])

    def test_unknown_target_does_not_display_all_course_teachers(self):
        for target in (None, {}, [], {"attributes": None},
                       {"attributes": {"course": {"lecturers": "教师甲"}}}):
            with self.subTest(target=target):
                pending, _ = self.questionnaires([{"id": "response-1", "target": target}])
                self.assertEqual(pending[0].display_title, "测试课程 未知教师")
                self.assertEqual(pending[0].JSXM, "")

    def test_target_teacher_names_are_cleaned_without_losing_joint_teachers(self):
        pending, _ = self.questionnaires([{"id": "response-1", "target": {
            "attributes": {"course": {"lecturers": [
                {"name": " 教师乙 "}, {"name": ""}, None, "教师甲", {},
                {"name": None}, {"name": 123}, {"name": "教师甲"}, {"name": "教师乙"},
            ]}},
        }}])
        self.assertEqual(pending[0].display_title, "测试课程 教师乙、教师甲")


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
