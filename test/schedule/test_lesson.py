import json
import unittest
from schedule import Lesson
from schedule.lesson import _lesson_object_hook


class TestLesson(unittest.TestCase):
    def test_serialize(self):
        lesson = Lesson("高等数学", "0001", ["张三", "李四"])
        d = lesson.dumps()
        self.assertEqual(d, {"class_name": "高等数学", "class_code": "0001", "teachers": ["张三", "李四"]})

    def test_deserialize(self):
        d = {"class_name": "高等数学", "class_code": "0001", "teachers": ["张三", "李四"]}
        lesson = Lesson.loads(d)
        self.assertEqual(lesson.class_name, "高等数学")
        self.assertEqual(lesson.class_code, "0001")
        self.assertEqual(lesson.teachers, ["张三", "李四"])
        self.assertIsNone(lesson.place)

    def test_legacy_serialized_lesson_without_place_uses_none(self):
        lesson = json.loads(
            '{"class_name":"高等数学","class_code":"0001","teachers":["张三"]}',
            object_hook=_lesson_object_hook,
        )

        self.assertIsInstance(lesson, Lesson)
        self.assertIsNone(lesson.place)

    def test_round_trip_preserves_present_place(self):
        lesson = Lesson("高等数学", "0001", ["张三"], "主楼 A101")

        restored = Lesson.loads(lesson.dumps())

        self.assertEqual(restored, lesson)
        self.assertEqual(restored.place, "主楼 A101")

    def test_both(self):
        lesson = Lesson("高等数学", "0001", ["张三", "李四"])
        d = lesson.dumps()
        lesson2 = Lesson.loads(d)
        self.assertEqual(lesson.class_name, lesson2.class_name)
        self.assertEqual(lesson.class_code, lesson2.class_code)
        self.assertEqual(lesson.teachers, lesson2.teachers)


if __name__ == '__main__':
    unittest.main()
