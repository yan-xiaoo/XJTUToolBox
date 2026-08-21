from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

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
    def current_week(self) -> int:
        try:
            start = datetime.strptime(self.start_date[:10], "%Y-%m-%d").date()
            return max(1, ((date.today() - start).days // 7) + 1)
        except ValueError:
            return 1


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
        if payload.get("code") != 200:
            raise ServerError(payload.get("code") or 1, payload.get("msg") or "查询校历失败")
        terms = []
        for item in payload.get("data") or []:
            holidays = [
                CalendarHoliday(
                    name=str(holiday.get("holiday_name") or ""),
                    start_date=str(holiday.get("start_date") or ""),
                    end_date=str(holiday.get("end_date") or ""),
                    days=str(holiday.get("holiday_days") or ""),
                    remark=str(holiday.get("holiday_remark") or ""),
                )
                for holiday in item.get("holidays") or []
            ]
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
        return terms
