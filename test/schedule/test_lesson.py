import unittest
from schedule import Lesson


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

    def test_both(self):
        lesson = Lesson("高等数学", "0001", ["张三", "李四"])
        d = lesson.dumps()
        lesson2 = Lesson.loads(d)
        self.assertEqual(lesson.class_name, lesson2.class_name)
        self.assertEqual(lesson.class_code, lesson2.class_code)
        self.assertEqual(lesson.teachers, lesson2.teachers)


if __name__ == '__main__':
    unittest.main()
