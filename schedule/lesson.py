import json


class Lesson:
    """
    一门课程。课程上课时间、上课周次等信息属于课表的一部分，不属于课程的属性。
    一门课程包含课程名，课程编号，课程教师和可选的上课地点三个信息。
    """
    def __init__(self, class_name, class_code, teachers, place=None):
        """
        :param class_name: 课程名
        :param class_code: 课程号
        :param teachers: 课程教师
        :param place: 上课地点，可以为空
        """
        self.class_name = class_name
        self.class_code = class_code
        self.teachers = teachers
        self.place = place

    def __repr__(self):
        return f"{self.class_name} 课程号: {self.class_code} 教师: {self.teachers} 地点: {self.place}"

    def __eq__(self, other):
        if not isinstance(other, Lesson):
            return False
        return self.class_name == other.class_name and self.class_code == other.class_code and self.teachers == other.teachers and self.place == other.place

    def dumps(self) -> dict:
        """
        将课程对象转换为字典输出
        """
        return {"class_name": self.class_name, "class_code": self.class_code,
                "teachers": self.teachers, "place": self.place}

    @classmethod
    def loads(cls, diction) -> "Lesson":
        """
        从字典中恢复课程对象信息
        """
        return cls(diction["class_name"], diction["class_code"], diction["teachers"], diction['place'])


class _LessonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Lesson):
            return o.dumps()
        return super().default(o)


def _lesson_object_hook(dct):
    if "class_name" in dct and "class_code" in dct and "teachers" in dct and 'place' in dct:
        return Lesson.loads(dct)
    return dct
