import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from auth import ServerError
from hello.profile import HelloProfile

TEST_DOMAIN = "schedule"


def _student(**overrides):
    student = {
        "name": "张三",
        "sno": "20230001",
        "sex": "1",
        "birthdate": "2005-01-02",
        "grade": "2023",
        "campusName": "兴庆校区",
        "academyName": "钱学森书院",
        "departmentName": "电气工程学院",
        "professionName": "080601 电气工程及其自动化",
        "className": "电气 001",
        "schoolingLen": "4",
        "enterSchoolDate": "2023-09-01",
        "cardId": "card-1",
        "pictureUrl": "https://example.com/student.jpg",
        "teacherBean": {
            "classTeaName": "王老师",
            "classTeaPhone": "10001",
            "counselorName": "李老师",
            "counselorPhone": "10002",
            "counselorOffLoca": "主楼 101",
        },
    }
    student.update(overrides)
    return student


def _payload(*, student=None, data_overrides=None, state=200, message="ok"):
    data = {"studentBean": _student() if student is None else student}
    if data_overrides:
        data.update(data_overrides)
    return {"state": state, "message": message, "data": data}


def _response(payload=None, *, error=None):
    json_call = Mock(side_effect=error) if error else Mock(return_value=payload)
    return SimpleNamespace(json=json_call)


class HelloProfileMappingTest(unittest.TestCase):
    def test_complete_student_and_teacher_payload_maps_every_field(self):
        profile = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(_payload())))).get_profile()
        self.assertEqual(profile.name, "张三")
        self.assertEqual(profile.student_no, "20230001")
        self.assertEqual(profile.sex, "男")
        self.assertEqual(profile.birthdate, "2005-01-02")
        self.assertEqual(profile.grade, "2023")
        self.assertEqual(profile.campus, "兴庆校区")
        self.assertEqual(profile.academy, "钱学森书院")
        self.assertEqual(profile.department, "电气工程学院")
        self.assertEqual(profile.major, "电气工程及其自动化")
        self.assertEqual(profile.class_name, "电气 001")
        self.assertEqual(profile.schooling_len, "4")
        self.assertEqual(profile.enter_school_date, "2023-09-01")
        self.assertEqual(profile.card_id, "card-1")
        self.assertEqual(profile.picture_url, "https://example.com/student.jpg")
        self.assertEqual(profile.class_teacher, "王老师")
        self.assertEqual(profile.class_teacher_phone, "10001")
        self.assertEqual(profile.counselor, "李老师")
        self.assertEqual(profile.counselor_phone, "10002")
        self.assertEqual(profile.counselor_office, "主楼 101")

    def test_missing_optional_fields_are_empty(self):
        profile = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(_payload(student={}))))).get_profile()
        for value in vars(profile).values():
            self.assertEqual(value, "")

    def test_gender_major_and_protocol_relative_picture_normalization(self):
        cases = (
            ("1", "男"),
            ("2", "女"),
            ("9", "9"),
        )
        for code, expected in cases:
            with self.subTest(code=code):
                student = _student(
                    sex=code,
                    professionName="2023080601   计算机科学与技术",
                    pictureUrl="",
                )
                profile = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(
                    _payload(student=student, data_overrides={"studentPictureUrl": "//example.com/a.jpg"})
                )))).get_profile()
                self.assertEqual(profile.sex, expected)
                self.assertEqual(profile.major, "计算机科学与技术")
                self.assertEqual(profile.picture_url, "http://example.com/a.jpg")

    def test_empty_picture_does_not_generate_a_bad_url(self):
        profile = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(
            _payload(student=_student(pictureUrl=""), data_overrides={"studentPictureUrl": ""})
        )))).get_profile()
        self.assertEqual(profile.picture_url, "")

    def test_nested_teacher_wins_and_top_level_teacher_is_fallback(self):
        nested = _student(teacherBean={"classTeaName": "nested"})
        top_level = {"classTeaName": "top-level", "counselorName": "fallback"}
        profile = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(
            _payload(student=nested, data_overrides={"teacherBean": top_level})
        )))).get_profile()
        self.assertEqual(profile.class_teacher, "nested")
        self.assertEqual(profile.counselor, "")

        no_nested = _student(teacherBean=None)
        fallback = HelloProfile(SimpleNamespace(get=Mock(return_value=_response(
            _payload(student=no_nested, data_overrides={"teacherBean": top_level})
        )))).get_profile()
        self.assertEqual(fallback.class_teacher, "top-level")
        self.assertEqual(fallback.counselor, "fallback")


class HelloProfileBoundaryTest(unittest.TestCase):
    def test_top_level_array_string_and_null_are_rejected_after_fallback(self):
        for value in (["array"], "string", None):
            with self.subTest(value=value):
                session = SimpleNamespace(get=Mock(side_effect=[_response(value), _response(value)]))
                with self.assertRaises(ServerError):
                    HelloProfile(session).get_profile()
                self.assertEqual(session.get.call_count, 2)

    def test_data_student_and_teacher_non_objects_are_rejected(self):
        payloads = (
            {"state": 200, "data": []},
            {"state": 200, "data": {"studentBean": []}},
            {"state": 200, "data": {"studentBean": {"teacherBean": []}}},
            {"state": 200, "data": {"studentBean": {}, "teacherBean": []}},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ServerError):
                    HelloProfile(SimpleNamespace(get=Mock(return_value=_response(payload)))).get_profile()

    def test_http_failure_and_broken_json_fall_back_to_https(self):
        for first in (requests.ConnectionError("http failed"), ValueError("broken json")):
            with self.subTest(error=type(first).__name__):
                first_response = first if isinstance(first, requests.RequestException) else _response(error=first)
                side_effect = [first_response, _response(_payload())]

                def get(*_args, **_kwargs):
                    value = side_effect.pop(0)
                    if isinstance(value, Exception):
                        raise value
                    return value

                session = SimpleNamespace(get=Mock(side_effect=get))
                self.assertEqual(HelloProfile(session).get_profile().name, "张三")
                self.assertEqual(session.get.call_count, 2)
                self.assertTrue(session.get.call_args_list[1].args[0].startswith("https://"))

    def test_valid_business_failure_does_not_fall_back(self):
        session = SimpleNamespace(get=Mock(return_value=_response(
            _payload(state=403, message="denied")
        )))
        with self.assertRaises(ServerError) as caught:
            HelloProfile(session).get_profile()
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(caught.exception.message, "denied")
        session.get.assert_called_once()

    def test_both_failures_preserve_meaningful_final_exception(self):
        first = requests.ConnectionError("http failed")
        final = requests.Timeout("https timed out")
        session = SimpleNamespace(get=Mock(side_effect=[first, final]))
        with self.assertRaises(requests.Timeout) as caught:
            HelloProfile(session).get_profile()
        self.assertIs(caught.exception, final)


if __name__ == "__main__":
    unittest.main()
