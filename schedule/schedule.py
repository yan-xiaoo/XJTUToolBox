from .lesson import Lesson, _LessonEncoder, _lesson_object_hook
from typing import Optional, Union
import json


class _ScheduleContainer:
    def __init__(self, weeks=20, days=7, periods=11, lessons=None):
        """
        :param weeks: 此课程表最多保存多少周的课程（默认20周）
        :param days: 此课程表最多保存每周多少天的课程（默认七天）
        :param periods: 每一天有几个可能的课程时间段（默认11段）
        """
        self.weeks = weeks
        self.days = days
        self.periods = periods
        self.lessons = lessons or {}

    def __getitem__(self, item) -> Union["WeekSchedule", None, Lesson]:
        pass

    def __eq__(self, other):
        if not isinstance(other, _ScheduleContainer):
            return False
        return self.weeks == other.weeks and self.days == other.days and self.periods == other.periods and \
            self.lessons == other.lessons

    def dumps(self):
        """
        将课程表转换为 JSON 字符串
        """
        diction = {"weeks": self.weeks, "days": self.days, "periods": self.periods,
                   "lessons": self.lessons}
        return json.dumps(diction, cls=_LessonEncoder)

    @classmethod
    def loads(cls, diction):
        """
        从 JSON 字符串中加载课程表
        :param diction: JSON 字符串
        :return: Schedule 对象
        """
        data = json.loads(diction, object_hook=_lesson_object_hook)
        return cls(data["weeks"], data["days"], data["periods"], data["lessons"])


class Schedule(_ScheduleContainer):
    def set(self, week: int, day: int, period: int, lesson: Lesson):
        """
        设置某一周某一天某一时间段的课程
        :param week: 周数, 1~self.weeks
        :param day: 星期几, 1~self.days
        :param period: 时间段, 1~self.periods
        :param lesson: 课程, Lesson对象
        """
        week = str(week)
        day = str(day)
        period = str(period)

        if week not in self.lessons:
            self.lessons[week] = {}
        if day not in self.lessons[week]:
            self.lessons[week][day] = {}
        self.lessons[week][day][period] = lesson

    def set_week_lessons(self, week: int, lessons: dict):
        """
        设置某一周的课程
        :param week: 周数, 1~self.weeks
        :param lessons: 课程表，格式为 {day: {period: lesson}}
        :return: None
        """
        week = str(week)
        self.lessons[week] = lessons

    def get(self, week: int, day: int, period: int) -> Optional[Lesson]:
        """
        获取某一周某一天某一时间段的课程。
        内部实现细节：内部字典的键其实是字符串（由于 JSON 的限制）
        :param week: 周数, 1~self.weeks
        :param day: 星期几, 1~self.days
        :param period: 时间段, 1~self.periods
        :return: 课程, 如果查询不到，则返回 None.
        """
        week = self.lessons.get(str(week))
        if week is None:
            return None
        else:
            day = week.get(str(day))
            if day is None:
                return None
            else:
                return day.get(str(period))

    def __getitem__(self, item) -> Union["WeekSchedule", None, Lesson, "DaySchedule"]:
        """
        获得一周，一天，或者一段时间的课程表。
        如果 item 是一个整数，比如 schedule[3]，则返回第三周的课表。
        如果 item 是一个二元组，比如 schedule[1, 3]，则返回第一周第三天（周三）的课表
        如果 item 是一个三元组，比如 schedule[1, 3, 4]，则返回第一周第三天（周三）第四节课的课程
        如果 item 是一个三元组且第三个位置是切片，比如 schedule[1, 3, 2:5]，则返回第一周第三天（周三）第2-4节课的课程

        如果 item 是一个元组，其的长度不能超过 3，并且第一个和第二个位置不能是切片对象，否则抛出 KeyError。
        如果查询不到给定时刻的课程，返回 None。
        """
        if isinstance(item, int):  # 一个整数，返回某一周的课程
            if item < 1 or item > self.weeks:
                raise KeyError("周数超出范围")
            return WeekSchedule(self.days, self.periods, self.lessons.get(str(item)))
        elif len(item) == 2:  # 二元组，返回某一天的课程
            if isinstance(item[0], slice) or isinstance(item[1], slice):
                raise KeyError("周数与天数不能为范围")
            if item[0] < 1 or item[0] > self.weeks or item[1] < 1 or item[1] > self.days:
                raise KeyError("周数或天数超出范围")
            return DaySchedule(self.periods, self.lessons.get(str(item[0]), {}).get(str(item[1])))
        elif len(item) == 3:
            if isinstance(item[0], slice) or isinstance(item[1], slice):  # 三元组，但第一、二位置是切片，出现异常
                raise KeyError("周数与天数不能为范围")
            if isinstance(item[2], slice):  # 三元组且最后一个位置是切片，返回一个时间段的课程
                start = item[2].start or 1
                stop = item[2].stop or self.periods
                step = item[2].step or 1
                if start < 1 or stop > self.periods or step < 1:
                    raise KeyError("时间段超出范围")
                return DaySchedule(self.periods, {k: v for k, v in self.lessons.get(str(item[0]), {}).get(str(item[1]), {}).items() if
                                                  start <= int(k) <= stop and (int(k) - start) % step == 0})
            elif isinstance(item[2], int):  # 三元组，返回某个时刻的课程
                return self.get(item[0], item[1], item[2])
        else:
            raise KeyError(f"无法识别 Key: {item}")

    @classmethod
    def loads(cls, diction):
        """
        从 JSON 字符串中加载课程表
        :param diction: JSON 字符串
        :return: Schedule 对象
        """
        data = json.loads(diction, object_hook=_lesson_object_hook)
        return cls(data["weeks"], data["days"], data["periods"], data["lessons"])


class WeekSchedule(_ScheduleContainer):
    """
    一周的课程表。此对象可以由切片 Schedule[week] 获取。
    """

    def __init__(self, days=7, periods=11, lessons=None):
        """
        :param days: 此课程表最多保存每周多少天的课程（默认七天）
        :param periods: 每一天有几个可能的课程时间段（默认11段）
        """
        super().__init__(1, days, periods, lessons)

    def get(self, day: int, period: int) -> Optional[Lesson]:
        """
        获取某一天某一时间段的课程
        :param day: 星期几, 1~self.days
        :param period: 时间段, 1~self.periods
        :return: 课程, 如果查询不到，则返回 None.
        """
        day = str(day)
        period = str(period)

        day = self.lessons.get(day)
        if day is None:
            return None
        else:
            return day.get(period)

    def set(self, day: int, period: int, lesson: Lesson):
        """
        设置某一天某一时间段的课程
        :param day: 星期几, 1~self.days
        :param period: 时间段, 1~self.periods
        :param lesson: 课程, Lesson对象
        """
        day = str(day)
        period = str(period)

        if day not in self.lessons:
            self.lessons[day] = {}
        self.lessons[day][period] = lesson

    def __getitem__(self, item):
        if isinstance(item, int):
            if item < 1 or item > self.days:
                raise KeyError("星期数超出范围")
            return DaySchedule(self.periods, self.lessons.get(str(item)))
        elif len(item) == 2:
            if isinstance(item[0], int) and isinstance(item[1], int):
                if item[0] < 1 or item[0] > self.days or item[1] < 1 or item[1] > self.periods:
                    raise KeyError("星期数或时间段超出范围")
                return self.get(item[0], item[1])
            elif isinstance(item[0], int) and isinstance(item[1], slice):
                start = item[1].start or 1
                stop = item[1].stop or self.periods
                step = item[1].step or 1
                if start < 1 or stop > self.periods or step < 1:
                    raise KeyError("时间段超出范围")
                return DaySchedule(self.periods, {k: v for k, v in self.lessons.get(str(item[0]), {}).items() if
                                                  start <= int(k) <= stop and (int(k) - start) % step == 0})
            else:
                raise KeyError("星期数超出范围")
        else:
            raise KeyError("星期数超出范围")

    @classmethod
    def loads(cls, diction):
        """
        从 JSON 字符串中加载课程表
        :param diction: JSON 字符串
        :return: Schedule 对象
        """
        data = json.loads(diction, object_hook=_lesson_object_hook)
        return cls(data["days"], data["periods"], data["lessons"])


class DaySchedule(_ScheduleContainer):
    """
    一天的课程表。此对象可以由切片 WeekSchedule[day] 获取。
    """

    def __init__(self, periods=11, lessons=None):
        """
        :param periods: 每一天有几个可能的课程时间段（默认11段）
        """
        super().__init__(1, 1, periods, lessons)

    def get(self, period: int) -> Optional[Lesson]:
        """
        获取某一时间段的课程
        :param period: 时间段, 1~self.periods
        :return: 课程, 如果查询不到，则返回 None.
        """
        return self.lessons.get(str(period))

    def set(self, period: int, lesson: Lesson):
        """
        设置某一时间段的课程
        :param period: 时间段, 1~self.periods
        :param lesson: 课程, Lesson对象
        """
        self.lessons[str(period)] = lesson

    def __getitem__(self, item):
        if isinstance(item, int):
            if item < 1 or item > self.periods:
                raise KeyError("时间段超出范围")
            return self.get(item)
        elif isinstance(item, slice):
            start = item.start or 1
            stop = item.stop or self.periods
            step = item.step or 1
            if start < 1 or stop > self.periods or step < 1:
                raise KeyError("时间段超出范围")
            return DaySchedule(self.periods, {k: v for k, v in self.lessons.items() if
                                              start <= int(k) <= stop and (int(k) - start) % step == 0})
        else:
            raise KeyError("时间段超出范围")

    @classmethod
    def loads(cls, diction):
        """
        从 JSON 字符串中加载课程表
        :param diction: JSON 字符串
        :return: Schedule 对象
        """
        data = json.loads(diction, object_hook=_lesson_object_hook)
        return cls(data["periods"], data["lessons"])


if __name__ == '__main__':
    schedule = Schedule(lessons={1: {1: {1: Lesson("数学", "001", "张三")}}})
    string = schedule.dumps()
    print("Dumped:", string)
    schedule2 = Schedule.loads(string)
    print(schedule2[1, 1, 1])
