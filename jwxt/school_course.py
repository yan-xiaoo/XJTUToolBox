from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from auth import ServerError


CAMPUS_OPTIONS = {
    "": "全部校区",
    "1": "兴庆校区",
    "2": "雁塔校区",
    "3": "曲江校区",
    "4": "苏州校区",
    "5": "创新港校区",
}

ELECTIVE_OPTIONS = {
    "": "全部",
    "06": "基础通识选修",
    "07": "基础通识核心",
    "08": "钱学森特色",
}


@dataclass
class SchoolCourse:
    course_code: str
    course_name: str
    class_code: str
    teachers: str
    department: str
    credit: str
    hours: str
    campus: str
    capacity: str
    selected: str
    time_place: str
    elective: str
    term: str


class SchoolCourseQuery:
    INIT_URL = "https://jwxt.xjtu.edu.cn/jwapp/sys/kcbcx/*default/index.do"
    CURRENT_TERM_URL = "https://jwxt.xjtu.edu.cn/jwapp/sys/kcbcx/modules/bjkcb/dqxnxq.do"
    TERM_LIST_URL = "https://jwxt.xjtu.edu.cn/jwapp/sys/kcbcx/modules/bjkcb/xnxqcx.do"
    DEPT_URL = "https://jwxt.xjtu.edu.cn/jwapp/code/44e02e19-e31b-4916-91b2-0a04380cbd3a.do"
    QUERY_URL = "https://jwxt.xjtu.edu.cn/jwapp/sys/kcbcx/modules/qxkcb/qxfbkccx.do"

    def __init__(self, session: requests.Session):
        self.session = session
        self._inited = False

    def _init(self) -> None:
        if self._inited:
            return
        self.session.get(self.INIT_URL, headers={"Accept": "text/html"}, timeout=20)
        self._inited = True

    def current_term(self) -> str:
        self._init()
        response = self.session.post(self.CURRENT_TERM_URL, timeout=15)
        rows = ((response.json().get("datas") or {}).get("dqxnxq") or {}).get("rows") or []
        return str((rows[0] or {}).get("DM") or "") if rows else ""

    def term_list(self) -> list[tuple[str, str]]:
        self._init()
        response = self.session.post(self.TERM_LIST_URL, data={"*order": "-DM"}, timeout=15)
        rows = ((response.json().get("datas") or {}).get("xnxqcx") or {}).get("rows") or []
        return [(str(row.get("DM") or ""), str(row.get("MC") or row.get("DM") or "")) for row in rows]

    def departments(self) -> list[tuple[str, str]]:
        self._init()
        response = self.session.post(self.DEPT_URL, timeout=15)
        rows = ((response.json().get("datas") or {}).get("code") or {}).get("rows") or []
        return [(str(row.get("id") or ""), str(row.get("name") or "")) for row in rows]

    def query(
            self,
            term: str,
            course_name: str = "",
            department: str = "",
            campus: str = "",
            weekday: str = "",
            start_section: str = "",
            end_section: str = "",
            elective: str = "",
            page: int = 1,
            page_size: int = 20) -> tuple[int, list[SchoolCourse]]:
        self._init()
        conditions: list = [
            {"name": "XNXQDM", "value": term, "linkOpt": "and", "builder": "equal"},
            [
                {"name": "RWZTDM", "value": "1", "linkOpt": "and", "builder": "equal"},
                {"name": "RWZTDM", "linkOpt": "or", "builder": "isNull"},
            ],
        ]
        if course_name:
            conditions.append({
                "name": "KCM", "caption": "课程名", "linkOpt": "AND",
                "builderList": "cbl_String", "builder": "include", "value": course_name,
            })
        if department:
            conditions.append({
                "name": "KKDWDM", "caption": "开课单位", "linkOpt": "AND",
                "builderList": "cbl_String", "builder": "equal", "value": department,
            })
        if campus:
            conditions.append({
                "name": "XXXQDM", "caption": "校区", "linkOpt": "AND",
                "builderList": "cbl_String", "builder": "equal", "value": campus,
            })
        if elective:
            conditions.append({
                "name": "XGXKLBDM", "caption": "选修类别", "linkOpt": "AND",
                "builderList": "cbl_m_List", "builder": "m_value_equal", "value": elective,
            })
        conditions.append({
            "name": "*order", "value": "+KKDWDM,+KCH,+KXH", "linkOpt": "AND", "builder": "m_value_equal",
        })
        response = self.session.post(
            self.QUERY_URL,
            data={
                "querySetting": json.dumps(conditions, ensure_ascii=False),
                "*order": "+KKDWDM,+KCH,+KXH",
                "SKXQ": weekday,
                "KSJC": start_section,
                "JSJC": end_section,
                "pageSize": str(page_size),
                "pageNumber": str(page),
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
        try:
            block = ((response.json().get("datas") or {}).get("qxfbkccx") or {})
        except ValueError as exc:
            raise ServerError(1, "全校课程接口返回了无法解析的数据") from exc
        courses = []
        for row in block.get("rows") or []:
            courses.append(SchoolCourse(
                course_code=str(row.get("KCH") or ""),
                course_name=str(row.get("KCM") or ""),
                class_code=str(row.get("KXH") or ""),
                teachers=str(row.get("SKJS") or ""),
                department=str(row.get("KKDWDM_DISPLAY") or ""),
                credit=str(row.get("XF") or ""),
                hours=str(row.get("XS") or ""),
                campus=str(row.get("XXXQDM_DISPLAY") or ""),
                capacity=str(row.get("KRL") or ""),
                selected=str(row.get("XKZRS") or row.get("NSXKRS") or ""),
                time_place=str(row.get("YPSJDD") or ""),
                elective=str(row.get("XGXKLBDM_DISPLAY") or ""),
                term=str(row.get("XNXQDM") or term),
            ))
        return int(block.get("totalSize") or len(courses)), courses
