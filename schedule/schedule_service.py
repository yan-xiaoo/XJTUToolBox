import datetime
import os.path
from peewee import SqliteDatabase, DoesNotExist, fn

from .schedule_database import Course, CourseInstance, create_tables, set_database, set_config, get_config, \
    DATABASE_VERSION, upgrade, downgrade, Term


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
        else:
            # 检查数据库版本
            try:
                current_version = int(get_config("database_version"))
            except (DoesNotExist, ValueError):
                current_version = 1
            if current_version < DATABASE_VERSION:
                upgrade(current_version, DATABASE_VERSION)
            elif current_version > DATABASE_VERSION:
                downgrade(current_version, DATABASE_VERSION)

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
        设置当前学期为某个学期。此操作不会创建新的学期，只会设置 config 中的 current_term 为此学期编号
        """
        set_config("current_term", term_number)

    def setTermInfo(self, term_number: str, start_date: str, current: bool = False):
        """
        设置学期信息。如果设置的学期已存在，将更新学期的开始时间；否则创建新的学期。
        :param term_number: 学期编号
        :param start_date: 学期开始日期
        :param current: 是否设置为当前学期，如果为 true，设置 config 中的 current_term 为此学期编号
        """
        term = Term.get_or_none(Term.term_number == term_number)
        if term is not None:
            term.start_date = start_date
            term.save()
        else:
            Term.create(term_number=term_number, start_date=start_date)

        if current:
            set_config("current_term", term_number)

    def getStartOfTerm(self):
        """
        获取学期的第一周的周一日期, 如果不存在则返回 None
        """
        try:
            current_term = self.getCurrentTerm()
            if current_term is None:
                return None
            day_string = Term.get(Term.term_number == current_term).start_date
            year, month, day = map(int, day_string.split("-"))
            return datetime.date(year, month, day)
        except DoesNotExist:
            return None

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

    def getSameCourseInOtherWeek(self, course: CourseInstance):
        """
        获得其他周中，和输入课程同日期同时间，且名称一致的其他课程
        :param course: 输入课程
        """
        return CourseInstance.select().where(CourseInstance.day_of_week == course.day_of_week,
                                             CourseInstance.start_time == course.start_time, CourseInstance.end_time == course.end_time,
                                             CourseInstance.course == course.course, CourseInstance.term_number == course.term_number)

    def getOtherCourseInSameTime(self, course: CourseInstance):
        """
        获得其他周中，和输入课程同一时间的其他（非同名）课程
        :param course: 输入课程
        """
        return CourseInstance.select(
            CourseInstance.course,
            CourseInstance.name,
            fn.GROUP_CONCAT(CourseInstance.week_number).alias('week_numbers'),
            CourseInstance.day_of_week,
            CourseInstance.start_time,
            CourseInstance.end_time,
            CourseInstance.term_number,
            CourseInstance.location,
            CourseInstance.teacher
        ).where(
            CourseInstance.start_time == course.start_time,
            CourseInstance.end_time == course.end_time,
            CourseInstance.course != course.course,
            CourseInstance.term_number == course.term_number,
            CourseInstance.day_of_week == course.day_of_week
        ).group_by(
            CourseInstance.course
        )

    def deleteCourseInWeeks(self, course: CourseInstance, weeks: list[int]):
        """
        删除课程表中的某几周的课程
        :param course: 课程对象，将删除此对象对应课程的部分周数
        :param weeks: 需要删除的周数
        """
        CourseInstance.delete().where(CourseInstance.course == course.course, CourseInstance.week_number.in_(weeks),
                                      CourseInstance.term_number == course.term_number, CourseInstance.day_of_week == course.day_of_week,
                                      CourseInstance.start_time == course.start_time, CourseInstance.end_time == course.end_time).execute()

    def addCourseInWeeks(self, course: CourseInstance, weeks: list[int]):
        """
        添加课程表中的某几周的课程
        :param course: 课程对象，将添加此对象对应课程的部分周数
        :param weeks: 需要添加的周数
        """
        insertion = []
        for week in weeks:
            insertion.append({
                "course": course.course,
                "name": course.name,
                "day_of_week": course.day_of_week,
                "start_time": course.start_time,
                "end_time": course.end_time,
                "location": course.location,
                "teacher": course.teacher,
                "week_number": week,
                "manual": 0,
                "term_number": course.term_number
            })
        CourseInstance.insert_many(insertion).execute()

    def editSingleCourse(self, course: CourseInstance, new_name: str, new_location: str, new_teacher: str):
        """
        修改课程表中的某一节课的名称、地点、教师
        :param course: 课程对象
        :param new_name: 新的课程名称
        :param new_location: 新的地点
        :param new_teacher: 新的教师
        """
        course.name = new_name
        course.location = new_location
        course.teacher = new_teacher
        course.save()

    def editMultiWeekCourse(self, course: CourseInstance, new_name: str, new_location: str, new_teacher: str):
        """
        修改课程表中的某一门课的名称、地点、教师。此操作会修改所有周数的课程
        :param course: 课程对象
        :param new_name: 新的课程名称
        :param new_location: 新的地点
        :param new_teacher: 新的教师
        """
        CourseInstance.update(name=new_name, location=new_location, teacher=new_teacher).where(
            CourseInstance.course == course.course, CourseInstance.term_number == course.term_number,
            CourseInstance.start_time == course.start_time, CourseInstance.end_time == course.end_time,
            CourseInstance.name == course.name, CourseInstance.day_of_week == course.day_of_week).execute()

    def addCourseFromJson(self, course_json: dict, merge_with_existing: bool = False, manual: bool = False):
        """
        从 json 添加课程
        :param course_json: 课程的 json 字典
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
        # 使用批量插入以加速
        insertion = []
        for week_no, single in enumerate(course_json["SKZC"]):
            if single == "1":
                insertion.append({
                    "course": course,
                    "day_of_week": day,
                    "start_time": start_time,
                    "end_time": end_time,
                    "location": location,
                    "teacher": teacher,
                    "week_number": week_no + 1,
                    "name": course_json["KCM"],
                    "manual": 1 if manual else 0,
                    "term_number": course_json["XNXQDM"]}
                )
        CourseInstance.insert_many(insertion).execute()
