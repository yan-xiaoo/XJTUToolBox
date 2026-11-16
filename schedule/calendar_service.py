"""Adapt the account's local timetable to xjtu-timetable-calendar.

No credentials, browser sessions or school requests cross this boundary.
Exports and subscriptions have separate baselines and cancellation ledgers.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from xjtu_calendar.academic_calendar import AcademicCalendar
from xjtu_calendar.config import Settings
from xjtu_calendar.exams import parse_exam_rows
from xjtu_calendar.fileutil import atomic_write_text
from xjtu_calendar.parser import ParseReport, TimetableParser
from xjtu_calendar.schedules import ScheduleTable
from xjtu_calendar.subscribe import load_state

from .xjtu_time import summer_time_dict, winter_time_dict
from .schedule_database import Config, database_proxy


def write_if_changed(path: Path, text: str) -> None:
    """Keep snapshot mtime stable so repeated publishing is a no-op."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == text.encode("utf-8"):
        return
    atomic_write_text(path, text, private=True)


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def default_schedule(first_day: date) -> dict:
    """Use the same periods and seasonal boundaries as the existing UI."""
    profiles = {}
    for key, table in (("summer", summer_time_dict), ("winter", winter_time_dict)):
        profiles[key] = {"periods": {
            str(n): [p["start"].strftime("%H:%M"), p["end"].strftime("%H:%M")]
            for n, p in table.items()
        }}
    periods = []
    for year in range(first_day.year - 1, first_day.year + 3):
        periods.extend([
            {"start": f"{year}-01-01", "end": f"{year}-04-30", "profile": "winter"},
            {"start": f"{year}-05-01", "end": f"{year}-09-30", "profile": "summer"},
            {"start": f"{year}-10-01", "end": f"{year}-12-31", "profile": "winter"},
        ])
    return {"profiles": profiles, "periods": periods}


class CalendarService:
    def __init__(self, account_directory: str | Path, term: str):
        # The term is used in filenames by the external engine as well.
        if not term or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", term):
            raise ValueError("学期编号无效")
        self.term = term
        self.account_directory = Path(account_directory).resolve()
        self.root = Path(account_directory) / "calendar" / term
        self.calendar_path = self.root / "calendar.json"
        self.schedule_path = self.root / "schedule.json"

    def settings(self, mode: str) -> Settings:
        if mode not in ("export", "subscription"):
            raise ValueError("未知日历模式")
        return Settings(home=self.root / mode, semester_key=self.term)

    def initialize(self, first_day: date) -> None:
        if first_day is None:
            raise ValueError("请先获取课表并设置学期开始日期")
        if first_day.weekday() != 0:
            raise ValueError("请先将学期开始日期设置为第 1 教学周的星期一")
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.calendar_path.exists():
            write_if_changed(self.calendar_path, json_text({
                "semester": {"key": self.term, "name": self.term,
                             "first_week_monday": first_day.isoformat()},
                "excluded_dates": [], "overrides": {},
            }))
        if not self.schedule_path.exists():
            write_if_changed(self.schedule_path, json_text(default_schedule(first_day)))

    def save_configuration(self, calendar: dict, schedule: dict) -> None:
        academic = AcademicCalendar.from_dict(calendar)
        if academic.semester.key != self.term:
            raise ValueError("校历中的学期编号必须与当前学期一致")
        problems = ScheduleTable.from_dict(schedule).validate()
        if problems:
            raise ValueError("；".join(problems))
        write_if_changed(self.calendar_path, json_text(calendar))
        write_if_changed(self.schedule_path, json_text(schedule))

    def snapshot(self, service) -> dict:
        """Read the database on its owning UI thread, before starting a job.

        Course database row IDs are recreated on refresh. Use the original
        Course name, scoped to this account, rather than those transient IDs.
        Instance display-name edits do not change that identity.
        """
        # Peewee models share a proxy: an old service is not an isolated reader.
        # Refuse stale/mismatched services before reading or creating any files.
        if (database_proxy.obj is not service.database
                or Path(service.database.database).resolve() != self.account_directory / 'schedule.db'):
            raise ValueError("账户数据库已切换，请关闭日历窗口后从当前账户重新打开")
        first_day = service.getStartOfTerm()
        if service.getCurrentTerm() != self.term or first_day is None:
            raise ValueError("请先获取当前学期课表并设置学期开始日期")
        self.initialize(first_day)
        academic = AcademicCalendar.from_file(self.calendar_path)
        if academic.semester.key != self.term:
            raise ValueError("校历中的学期编号与当前学期不一致")
        if academic.semester.first_week_monday != first_day:
            raise ValueError("学期开始日期已变更，请在日历配置中核对第 1 周星期一")
        # Account-local namespace remains stable even if the account directory moves.
        identity_path = self.root.parent / "identity.json"
        if not identity_path.exists():
            from uuid import uuid4
            write_if_changed(identity_path, json_text({"namespace": uuid4().hex}))
        namespace = json.loads(identity_path.read_text(encoding="utf-8"))["namespace"]

        def course_key(row):
            original_name = row.course.name
            return "toolbox-" + hashlib.sha256(
                f"{namespace}|{original_name}".encode("utf-8")
            ).hexdigest()[:24]

        courses = []
        for row in service.getCourseInTerm(self.term):
            if not 1 <= row.week_number <= 366 or not 1 <= row.day_of_week <= 7:
                raise ValueError("课表中存在无效周次或星期，已停止导出")
            if not 1 <= row.start_time <= row.end_time <= 11:
                raise ValueError("课表中存在无效节次，已停止导出")
            courses.append({"KCH": course_key(row), "KCM": row.name,
                            "SKJS": row.teacher or "", "JASMC": row.location or "",
                            "SKXQ": row.day_of_week, "KSJC": row.start_time,
                            "JSJC": row.end_time, "weeks": [row.week_number]})
        if not courses:
            raise ValueError("当前学期没有课程；请先获取课表，空课表不会用于发布撤销")
        slots = {}
        for row in courses:
            slot = (row["KCH"], row["SKXQ"], tuple(row["weeks"]), row["KSJC"], row["JSJC"])
            if slot in slots and slots[slot] != row:
                raise ValueError("同名课程在同一时段存在不同安排，无法可靠区分，请先核对课表")
            slots[slot] = row
        parser = TimetableParser(expansion_limit=366)
        parser.parse(courses)
        report = parser.report
        if report.skipped or report.parsed != len(courses):
            raise ValueError("部分课程无法转换，已停止导出")

        exams = []
        for row in service.getExamInTerm(self.term):
            if not 1 <= row.day_of_week <= 7 or row.week_number < 1:
                raise ValueError("考试中存在无效周次或星期")
            day = first_day + timedelta(days=(row.week_number - 1) * 7 + row.day_of_week - 1)
            if row.end_exact_time <= row.start_exact_time:
                raise ValueError("考试结束时间必须晚于开始时间")
            # The source DB has no upstream exam ID. Do not invent one: the
            # engine uses its documented time-based fallback on rescheduling.
            exams.append({"KCH": course_key(row), "KCM": row.course.name,
                          "KSRQ": day.isoformat(), "KSSJMS":
                          f"{row.start_exact_time:%H:%M}-{row.end_exact_time:%H:%M}",
                          "JASMC": row.location or "", "ZWH": row.seat_number or ""})
        marker = Config.get_or_none(Config.key == f"calendar_exams_complete_{self.term}")
        complete = marker is not None and marker.value == "1"
        exam_payload = {"datas": {"toolbox": {"rows": exams, "extParams": {"code": 1 if complete else 0}}}}
        exam_report = ParseReport()
        parse_exam_rows(exam_payload, report=exam_report)
        if exam_report.skipped:
            raise ValueError("部分考试无法转换，已停止导出")
        return {"courses": courses, "exams": exam_payload}

    def prepare(self, snapshot: dict, mode: str, *, excluded_dates=()) -> Settings:
        cfg = self.settings(mode)
        cfg.ensure_dirs()
        calendar = json.loads(self.calendar_path.read_text(encoding="utf-8"))
        calendar["excluded_dates"] = sorted(set(calendar.get("excluded_dates", [])) |
                                             {d.isoformat() for d in excluded_dates})
        AcademicCalendar.from_dict(calendar)
        ScheduleTable.from_file(self.schedule_path)
        write_if_changed(cfg.semester_config_path(self.term), json_text(calendar))
        write_if_changed(cfg.schedule_config_path(), self.schedule_path.read_text(encoding="utf-8"))
        for path, data, prev in (
            (cfg.raw_timetable_path(self.term), snapshot["courses"], cfg.raw_timetable_prev_path(self.term)),
            (cfg.raw_exams_path(self.term), snapshot["exams"], cfg.raw_exams_prev_path(self.term)),
        ):
            text = json_text(data)
            if path.is_file() and path.read_bytes() != text.encode("utf-8"):
                write_if_changed(prev, path.read_text(encoding="utf-8"))
            write_if_changed(path, text)
        return cfg

    def subscription_state(self):
        return load_state(self.settings("subscription"), self.term)
