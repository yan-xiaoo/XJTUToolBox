import datetime
import os.path
from typing import List

from peewee import SqliteDatabase, DoesNotExist, fn

from .schedule_database import Course, Exam, CourseInstance, create_tables, set_database, set_config, get_config, \
    DATABASE_VERSION, upgrade, downgrade, Term

weekday_map = {
    "星期一": 1,
    "星期二": 2,
    "星期三": 3,
    "星期四": 4,
    "星期五": 5,
    "星期六": 6,
    "星期日": 7,
    "星期天": 7,  # 有些写法用“星期天”
}


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

    def clearAllCourses(self, term_number: str = None):
        """
        清除所有课程
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        CourseInstance.delete().where(CourseInstance.term_number == term_number).execute()

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

    def getExamInTerm(self, term_number: str = None):
        """
        获取某个学期的考试安排
        :param term_number: 学期编号
        :return: 考试安排
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return Exam.select().where(Exam.term_number == term_number)

    def getCourseInTerm(self, term_number: str = None):
        """
        获取某个学期的课程表
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return CourseInstance.select().where(CourseInstance.term_number == term_number)

    def getExamInWeek(self, week_number: int, term_number: str = None):
        """
        获取某一周的考试安排
        :param week_number: 周数
        :param term_number: 学期编号
        :return: 考试安排
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return Exam.select().where(Exam.week_number == week_number, Exam.term_number == term_number)

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

    def getOneCourseInCertainTime(self, day_of_week: int, start_time: int, end_time: int, week: int, term_number: str = None):
        """
        获取某一时间段（某一天的某一时间）中某一周的课程
        :param day_of_week: 星期几
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param week: 周数
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return CourseInstance.select().where(
            CourseInstance.day_of_week == day_of_week,
            CourseInstance.start_time == start_time,
            CourseInstance.end_time == end_time,
            CourseInstance.week_number == week,
            CourseInstance.term_number == term_number
        )

    def getCourseInCertainTime(self, day_of_week: int, start_time: int, end_time: int, term_number: str = None):
        """
        获取某一时间段（某一天的某一时间）中，不同周的所有的课程
        :param day_of_week: 星期几
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        return CourseInstance.select().where(
            CourseInstance.day_of_week == day_of_week,
            CourseInstance.start_time == start_time,
            CourseInstance.end_time == end_time,
            CourseInstance.term_number == term_number
        )

    def getCourseGroupInCertainTime(self, day_of_week: int, start_time: int, end_time: int, term_number: str = None):
        """
        获取某一时间段（某一天的某一时间）中，不同周的所有的课程
        :param day_of_week: 星期几
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param term_number: 学期编号
        :return: 课程表
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
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
            CourseInstance.day_of_week == day_of_week,
            CourseInstance.start_time == start_time,
            CourseInstance.end_time == end_time,
            CourseInstance.term_number == term_number
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
                "manual": course.manual,
                "status": 7 if course.manual else 1,
                "term_number": course.term_number,
                "Exam": course.Exam
            })
        CourseInstance.insert_many(insertion).execute()

    def editExam(self, exam: Exam, new_name: str, new_location: str, new_seat_number: str):
        """
        修改考试的名称、地点、座位号
        """
        exam.name = new_name
        exam.location = new_location
        exam.seat_number = new_seat_number
        exam.save()

    def deleteExam(self, exam: Exam):
        """
        删除考试
        :param exam: 考试对象
        """
        exam.delete_instance()

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

    def addCourse(self, course_name: str, day_of_week: int, start_time: int, end_time: int, location: str, teacher: str, week_numbers: List[int], term_number: str = None):
        """
        添加课程
        :param course_name: 课程名称
        :param day_of_week: 星期几
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param location: 地点
        :param teacher: 教师
        :param week_numbers: 此课程的所有周数
        :param term_number: 学期编号
        """
        if term_number is None:
            term_number = self.getCurrentTerm()
        course = Course.get_or_create(name=course_name)[0]
        insertion = []
        for week in week_numbers:
            insertion.append({
                "course": course,
                "name": course_name,
                "day_of_week": day_of_week,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "teacher": teacher,
                "week_number": week,
                "manual": 1,
                "status": 7,   # 无需考勤
                "term_number": term_number
            })
        CourseInstance.insert_many(insertion).execute()

    def getCourseGroupFromJson(self, course_json: dict, manual: bool = False):
        """
        从 json 文件中创建课程对象，且将不同周的课程创建为一个对象，周数记录到返回结果的 week_numbers 列表中
        :param course_json: 课程的 json 字典
        :param manual: 课程的 manual 字段如何设置，即标记课程是不是手动添加的
        """
        weeks = []
        teacher = course_json.get("SKJS", None)
        location = course_json.get("JASMC", None)
        day = int(course_json["SKXQ"])
        start_time = int(course_json["KSJC"])
        end_time = int(course_json["JSJC"])
        for week_no, single in enumerate(course_json["SKZC"]):
            if single == "1":
                weeks.append(week_no + 1)
        result = CourseInstance(course=None,
                                name=course_json["KCM"],
                                day_of_week=day,
                                start_time=start_time,
                                end_time=end_time,
                                location=location,
                                teacher=teacher,
                                week_number=None,
                                manual=1 if manual else 0,
                                term_number=course_json["XNXQDM"],
                                week_numbers=weeks)
        return result

    def getCourseFromJson(self, course_json: dict, manual: bool = False) -> List[CourseInstance]:
        """
        从 json 文件中创建课程对象，
        :param course_json: 课程的 json 字典
        :param manual: 课程的 manual 字段如何设置，即标记课程是不是手动添加的
        """

        result = []
        teacher = course_json.get("SKJS", None)
        location = course_json.get("JASMC", None)
        day = int(course_json["SKXQ"])
        start_time = int(course_json["KSJC"])
        end_time = int(course_json["JSJC"])
        #
        for week_no, single in enumerate(course_json["SKZC"]):
            if single == "1":
                result.append(
                    CourseInstance(course=None,
                                   name=course_json["KCM"],
                                   day_of_week=day,
                                   start_time=start_time,
                                   end_time=end_time,
                                   location=location,
                                   teacher=teacher,
                                   week_number=week_no + 1,
                                   manual=1 if manual else 0,
                                   term_number=course_json["XNXQDM"]))

        return result

    def addExamFromJson(self, exam_json: dict):
        """
        从 json 文件中创建考试对象，
        :param exam_json: 考试的 json 字典
        """
        result = []

        exams = exam_json["exams"]
        term_number = exam_json["term_number"]
        for one in exams:
            time_string = one.get("KSSJMS", "")
            date_part, time_part = time_string.split(' ')
            time_range = time_part.split('(')[0]  # 去掉 (星期二)
            start_str, end_str = time_range.split('-')

            location = one.get("JASMC", "")
            seat_number = one.get("ZWH", "")

            course = Course.get_or_create(name=one["KCM"])[0]

            # 构造 datetime 对象
            start_dt = datetime.datetime.fromisoformat(f"{date_part}T{start_str}")
            end_dt = datetime.datetime.fromisoformat(f"{date_part}T{end_str}")

            if Exam.select().where(Exam.course == course).count() != 0:
                # 如果已经存在同名考试，则删除原先考试，重新添加
                Exam.delete().where(Exam.course == course).execute()

            '''
            这里的时间是粗略的，毕竟考试的时间并不总是严格与课程节次重合
            由于课表本身设计就不是用来展示任意时间的日程的，其实没办法精确展示。
            '''
            if 8 < start_dt.hour < 12:
                start_time = start_dt.hour - 7
            elif 12 <= start_dt.hour < 18:
                start_time = start_dt.hour - 9
            elif 18 <= start_dt.hour < 24:
                start_time = start_dt.hour - 10
            else:
                start_time = 1

            end_time = start_time + 1

            week = (start_dt.date() - self.getStartOfTerm()).days // 7 + 1
            day_of_week = start_dt.isoweekday()  # 获取 ISO 周几（1-7）

            exam = Exam(name=one["KCM"] + "考试",
                        week_number=week,
                        course=course,
                        location=location,
                        seat_number=seat_number,
                        day_of_week=day_of_week,
                        start_time=start_time,
                        end_time=end_time,
                        term_number=term_number,
                        start_exact_time=start_dt.time(),
                        end_exact_time=end_dt.time())
            result.append(exam)

        with self.database.atomic():
            Exam.bulk_create(result)

    def addCourseFromGroup(self, course_group, merge_with_existing: bool = False):
        """
        添加课程表的内容
        :param course_group: 课程的 json 字典，其中 week_numbers 字段表示课程的所有周数
        :param merge_with_existing: 如果已存在名称相同的课程，将当前课程视为此课程的实例，而不新建课程
        """
        # 创建课程表的内容
        if merge_with_existing:
            course = Course.get_or_create(name=course_group.name)[0]
        else:
            course = Course.create(name=course_group.name)
        # 解析 json 并添加课程实例表的内容
        insertion = []
        for week in course_group.week_numbers:
            insertion.append(
                CourseInstance(course=course,
                               name=course_group.name,
                               day_of_week=course_group.day_of_week,
                               start_time=course_group.start_time,
                               end_time=course_group.end_time,
                               location=course_group.location,
                               teacher=course_group.teacher,
                               week_number=week,
                               manual=course_group.manual,
                               term_number=course_group.term_number,
                               Exam=course_group.Exam))
        with self.database.atomic():
            CourseInstance.bulk_create(insertion)

    def deleteCourseFromGroup(self, course_group):
        """
        删除课程表的内容
        :param course_group: 课程的 json 字典，其中 week_numbers 字段表示课程要删除的所有周数
        """
        CourseInstance.delete().where(
            CourseInstance.course == course_group.course,
            CourseInstance.term_number == course_group.term_number,
            CourseInstance.start_time == course_group.start_time,
            CourseInstance.end_time == course_group.end_time,
            CourseInstance.name == course_group.name,
            CourseInstance.day_of_week == course_group.day_of_week,
            CourseInstance.week_number.in_(
                course_group.week_numbers)).execute()

    def addCourseFromJson(self,
                          course_json: dict,
                          merge_with_existing: bool = False,
                          manual: bool = False):
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
        insertion = self.getCourseFromJson(course_json, manual)
        if insertion is None:
            return
        for item in insertion:
            item.course = course
        with self.database.atomic():
            CourseInstance.bulk_create(insertion)

    def deleteMultiWeekCourse(self, course: CourseInstance):
        """
        删除课程表中的某一门课的所有周数的课程
        :param course: 课程对象
        """
        CourseInstance.delete().where(
            CourseInstance.course == course.course,
            CourseInstance.term_number == course.term_number,
            CourseInstance.start_time == course.start_time,
            CourseInstance.end_time == course.end_time,
            CourseInstance.name == course.name,
            CourseInstance.day_of_week == course.day_of_week).execute()
