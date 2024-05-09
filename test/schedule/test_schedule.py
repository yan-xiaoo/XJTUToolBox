import unittest
from schedule import WeekSchedule, DaySchedule, Schedule, Lesson


class TestSchedule(unittest.TestCase):
    def setUp(self):
        self.schedule = Schedule(lessons={'1': {'1': {'1': Lesson("数学", "001", "张三")}},
                                          '2': {'1': {'1': Lesson("数学", "002", "李四"),
                                                      '2': Lesson("数学", "003", "王五")}}})

    def test_schedule_dump_load(self):
        dumped = self.schedule.dumps()
        loaded = Schedule.loads(dumped)
        self.assertEqual(self.schedule, loaded)

    def test_schedule_slice(self):
        sliced = self.schedule[2]
        correct = WeekSchedule(lessons={'1': {'1': Lesson("数学", "002", "李四"),
                                              '2': Lesson("数学", "003", "王五")}})
        self.assertEqual(sliced, correct)
        sliced_2 = self.schedule[2, 1]
        correct_2 = DaySchedule(lessons={'1': Lesson("数学", "002", "李四"),
                                         '2': Lesson("数学", "003", "王五")})
        self.assertEqual(sliced_2, correct_2)
        sliced_3 = self.schedule[2, 1, 1]
        correct_3 = Lesson("数学", "002", "李四")
        self.assertEqual(sliced_3, correct_3)
        sliced_4 = self.schedule[2, 1, 1:2]
        correct_4 = DaySchedule(lessons={'1': Lesson("数学", "002", "李四"),
                                         '2': Lesson("数学", "003", "王五")})
        self.assertEqual(sliced_4, correct_4)

    def test_week_schedule_slice(self):
        week_schedule = self.schedule[2]
        sliced = week_schedule[1]
        correct = DaySchedule(lessons={'1': Lesson("数学", "002", "李四"),
                                       '2': Lesson("数学", "003", "王五")})
        self.assertEqual(sliced, correct)
        sliced_2 = week_schedule[1, 1]
        correct_2 = Lesson("数学", "002", "李四")
        self.assertEqual(sliced_2, correct_2)
        sliced_3 = week_schedule[1, 1:2]
        self.assertEqual(sliced_3, correct)

    def test_day_schedule_slice(self):
        day_schedule = self.schedule[2, 1]
        sliced = day_schedule[1]
        correct = Lesson("数学", "002", "李四")
        self.assertEqual(sliced, correct)
        sliced_2 = day_schedule[1:2]
        correct_2 = DaySchedule(lessons={'1': Lesson("数学", "002", "李四"),
                                         '2': Lesson("数学", "003", "王五")})
        self.assertEqual(sliced_2, correct_2)

    def test_set_week_lesson(self):
        self.schedule.set_week_lessons(3, {'1': {'1': Lesson("数学", "001", "张三")}})
        self.assertEqual(self.schedule[3], WeekSchedule(lessons={'1': {'1': Lesson("数学", "001", "张三")}}))


if __name__ == '__main__':
    unittest.main()
