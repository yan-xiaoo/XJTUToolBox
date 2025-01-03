import datetime
import os.path
from peewee import SqliteDatabase, DoesNotExist

from .schedule_database import Course, CourseInstance, create_tables, set_database, set_config, get_config


class ScheduleService:
    """处理课程表插入、删除、修改等常见操作的服务类"""
    def __init__(self, database_path: str):
        """
        连接到 Sqlite 数据库，并且（可选的）创建表
        :param database_path: 数据库文件路径
        如果此路径不存在，则会创建一个新的 sqlite 数据库并建表。
        """
        self.database = SqliteDatabase(database_path)
        set_database(self.database)
        if not os.path.exists(database_path):
            create_tables(self.database)

    def clearNonManualCourses(self, term_number: str = None):
        """
        清除所有非手动添加的课程
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        CourseInstance.delete().where(CourseInstance.manual == 0, CourseInstance.term_number == term_number).execute()

    def selectCourse(self, *args):
        """
        查询课程
        """
        return CourseInstance.select().where(*args)

    def getCurrentTerm(self):
        """
        获取当前学期，如果不存在则返回 None
        """
        try:
            return get_config("current_term")
        except DoesNotExist:
            return None

    def setCurrentTerm(self, term_number: str):
        """
        设置当前学期
        """
        set_config("current_term", term_number)

    def getStartOfTerm(self):
        """
        获取学期的第一周的周一日期, 如果不存在则返回 None
        """
        try:
            day_string = get_config("start_of_term")
            year, month, day = map(int, day_string.split("-"))
            return datetime.date(year, month, day)
        except DoesNotExist:
            return None

    def setStartOfTerm(self, start_date: datetime.date):
        """
        设置学期的第一周的周一日期
        """
        set_config("start_of_term", f"{start_date.year}-{start_date.month}-{start_date.day}")

    def getCourseInTerm(self, term_number: str = None):
        """
        获取某个学期的课程表
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return CourseInstance.select().where(CourseInstance.term_number == term_number)

    def getCourseInWeek(self, week_number: int, term_number: str = None):
        """
        获取某一周的课程表
        :param week_number: 周数
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return CourseInstance.select().where(CourseInstance.week_number == week_number, CourseInstance.term_number == term_number)

    def addCourseFromJson(self, course_json: dict, merge_with_existing: bool = False, manual: bool = False):
        """
        从 json 添加课程
        :param course_json: 课程的 json 字典
        :param term_number: 学期编号，比如 2023-2024-1
        :param merge_with_existing: 如果已存在名称相同的课程，将当前课程视为此课程的实例，而不新建课程
        :param manual: 是否为手动添加的课程
        """
        # 创建课程表的内容
        if merge_with_existing:
            course = Course.get_or_create(name=course_json["KCM"])[0]
        else:
            course = Course.create(name=course_json["KCM"])
        # 解析 json 并添加课程实例表的内容
        teacher = course_json.get("SKJS", None)
        location = course_json.get("JASMC", None)
        day = int(course_json["SKXQ"])
        start_time = int(course_json["KSJC"])
        end_time = int(course_json["JSJC"])
        for week_no, single in enumerate(course_json["SKZC"]):
            if single == "1":
                CourseInstance.create(
                    course=course,
                    day_of_week=day,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    teacher=teacher,
                    week_number=week_no + 1,
                    manual=1 if manual else 0,
                    term_number=course_json["XNXQDM"]
                )
