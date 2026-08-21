from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Mapping

import requests

from auth import ServerError


@dataclass
class CalendarTerm:
    term_id: str
    start_date: str
    end_date: str
    term_num: str
    year_num: str
    week_number: str
    work_days: str
    holidays: list["CalendarHoliday"] = field(default_factory=list)

    @property
    def current_week(self) -> int | None:
        try:
            start = datetime.strptime(self.start_date[:10], "%Y-%m-%d").date()
            end = datetime.strptime(self.end_date[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
        today = date.today()
        if today < start or today > end:
            return None
        week = ((today - start).days // 7) + 1
        try:
            cap = int(self.week_number)
        except (TypeError, ValueError):
            return None
        if cap <= 0:
            return None
        return min(week, cap)


@dataclass
class CalendarHoliday:
    name: str
    start_date: str
    end_date: str
    days: str
    remark: str


class SchoolCalendar:
    SHOW_URL = "http://one2020.xjtu.edu.cn/EIP/edu/education/schoolcalendar/showCalendar.htm"
    TERMS_URL = "http://one2020.xjtu.edu.cn/EIP/schoolcalendar/terms.htm"

    def __init__(self, session: requests.Session):
        self.session = session

    def get_terms(self) -> list[CalendarTerm]:
        try:
            self.session.get(self.SHOW_URL, timeout=15)
        except requests.RequestException:
            pass
        response = self.session.post(
            self.TERMS_URL,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "http://one2020.xjtu.edu.cn",
                "Referer": self.SHOW_URL,
            },
            timeout=20,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServerError(1, "校历接口返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise ServerError(1, "校历接口返回了无法解析的数据")
        if payload.get("code") != 200:
            raise ServerError(payload.get("code") or 1, payload.get("msg") or "查询校历失败")
        raw_terms = payload.get("data")
        if raw_terms is None:
            raw_terms = []
        if not isinstance(raw_terms, list):
            raise ServerError(1, "校历接口返回了无法解析的数据")
        terms = []
        for item in raw_terms:
            if not isinstance(item, Mapping):
                raise ServerError(1, "校历接口返回了无法解析的数据")
            raw_holidays = item.get("holidays")
            if raw_holidays is None:
                raw_holidays = []
            if not isinstance(raw_holidays, list):
                raise ServerError(1, "校历接口返回了无法解析的数据")
            holidays = []
            for holiday in raw_holidays:
                if not isinstance(holiday, Mapping):
                    raise ServerError(1, "校历接口返回了无法解析的数据")
                holidays.append(CalendarHoliday(
                    name=str(holiday.get("holiday_name") or ""),
                    start_date=str(holiday.get("start_date") or ""),
                    end_date=str(holiday.get("end_date") or ""),
                    days=str(holiday.get("holiday_days") or ""),
                    remark=str(holiday.get("holiday_remark") or ""),
                ))
            terms.append(CalendarTerm(
                term_id=str(item.get("id") or ""),
                start_date=str(item.get("start_date") or ""),
                end_date=str(item.get("end_date") or ""),
                term_num=str(item.get("term_num") or ""),
                year_num=str(item.get("year_num") or ""),
                week_number=str(item.get("week_number") or ""),
                work_days=str(item.get("work_days") or ""),
                holidays=holidays,
            ))
        terms.sort(key=lambda term: (term.start_date, term.term_id), reverse=True)
        return terms
