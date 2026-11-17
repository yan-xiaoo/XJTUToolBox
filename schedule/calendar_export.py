"""Shared ICS serialization extracted from ScheduleInterface.export."""
import datetime
import hashlib
import json

import pytz
from icalendar import Calendar, Alarm, Event
from schedule import getClassStartTime, getClassEndTime
from schedule.xjtu_time import isSummerTime
from schedule.schedule_database import Config, Term, Course, CourseInstance, Exam


def build_calendar(service, ignore_holidays=(), set_alarm=True, *, uid_namespace="",
                   tr=lambda text: text, stamp=None):
    # DatabaseProxy is shared by ScheduleService instances. Bind only while
    # materializing on the caller/UI thread; HTTP threads receive bytes only.
    with service.database.bind_ctx([Config, Term, Course, CourseInstance, Exam]):
        return _build_calendar(service, ignore_holidays, set_alarm, uid_namespace, tr, stamp)


def _build_calendar(service, ignore_holidays, set_alarm, uid_namespace, tr, stamp):
    LOCAL_TIMEZONE = pytz.timezone("Asia/Shanghai")  # 设定为北京时间
    term_start = service.getStartOfTerm()
    if term_start is None:
        raise ValueError("学期开始时间为空")

    cal = Calendar()
    cal.add("version", "2.0")
    cal.add("prodid", "-//XJTUToolBox//Schedule//ZH")
    cal.add("x-wr-calname", tr("课程表"))
    stamp = stamp or datetime.datetime.now(datetime.timezone.utc)
    term = service.getCurrentTerm()
    seen = {}

    def identify(event, kind, name, week, day, start):
        key = json.dumps([uid_namespace, term, kind, name, week, day, str(start)], ensure_ascii=False)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        uid = hashlib.sha256(f"{key}:{ordinal}".encode("utf-8")).hexdigest()
        event.add("uid", f"{uid}@xjtutoolbox")
        event.add("dtstamp", stamp)
        event.add("last-modified", stamp)

    for course in service.getCourseInTerm():

        term_start_time = datetime.datetime(term_start.year,
                                            term_start.month,
                                            term_start.day)
        date = term_start_time + datetime.timedelta(
            days=(course.week_number - 1) * 7 + course.day_of_week - 1)

        e = Event()
        name = course.name if course.name else ""
        location = course.location if course.location else ""
        e.add("summary", name)
        e.add("description", f"{name} {location}")
        # 有的课程可能没有地点信息，如果没有就不添加这个字段
        if location:
            e.add('location', location)

        if date.date() in ignore_holidays:
            continue

        begin_time = getClassStartTime(course.start_time,
                                       isSummerTime(date))
        end_time = getClassEndTime(course.end_time, isSummerTime(date))

        e.add(
            "dtstart",
            LOCAL_TIMEZONE.localize(
                date.replace(hour=begin_time.hour,
                             minute=begin_time.minute)))
        e.add(
            "dtend",
            LOCAL_TIMEZONE.localize(
                date.replace(hour=end_time.hour,
                             minute=end_time.minute)))

        if set_alarm:
            alarm = Alarm()
            alarm.add("action", "display")
            alarm.add("description", tr("上课提醒"))
            alarm.add("trigger", datetime.timedelta(minutes=-15))
            e.add_component(alarm)

        identify(e, "course", name, course.week_number, course.day_of_week, course.start_time)
        cal.add_component(e)

    for exam in service.getExamInTerm():
        term_start_time = datetime.datetime(term_start.year,
                                            term_start.month,
                                            term_start.day)
        date = term_start_time + datetime.timedelta(
            days=(exam.week_number - 1) * 7 + exam.day_of_week - 1)

        e = Event()
        e.add("summary", exam.name)
        e.add("description", tr("座位号:") + (exam.seat_number or ""))
        e.add('location', exam.location)

        begin_time = exam.start_exact_time
        end_time = exam.end_exact_time

        e.add(
            "dtstart",
            LOCAL_TIMEZONE.localize(
                date.replace(hour=begin_time.hour,
                             minute=begin_time.minute)))
        e.add(
            "dtend",
            LOCAL_TIMEZONE.localize(
                date.replace(hour=end_time.hour,
                             minute=end_time.minute)))

        if set_alarm:
            alarm = Alarm()
            alarm.add("action", "display")
            alarm.add("description", tr("考试提醒"))
            alarm.add("trigger", datetime.timedelta(minutes=-30))
            e.add_component(alarm)

        identify(e, "exam", exam.name, exam.week_number, exam.day_of_week, exam.start_exact_time)
        cal.add_component(e)
    return cal.to_ical()
