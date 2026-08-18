from __future__ import annotations

from dataclasses import dataclass, field

import requests

from auth import ServerError
from .homepage import (
    FACULTY_HOST,
    HomepageResult,
    absolute_url,
    decode_page,
    is_standard_homepage,
    is_unavailable_page,
    looks_like_json,
    parse_filter_options,
    parse_homepage,
)


@dataclass
class FacultyFilter:
    colleges: list[tuple[str, str]] = field(default_factory=list)
    disciplines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FacultyMember:
    teacher_id: str
    name: str
    english_name: str = ""
    college: str = ""
    rank: str = ""
    job: str = ""
    discipline: str = ""
    degree: str = ""
    education: str = ""
    graduated: str = ""
    url: str = ""
    email: str = ""
    contact: str = ""
    phone: str = ""
    mobile: str = ""
    office: str = ""
    address: str = ""
    entry_time: str = ""
    profile: str = ""
    research_list: list[str] = field(default_factory=list)
    doctoral_tutor: bool = False
    master_tutor: bool = False
    pic_url: str = ""

    @property
    def research(self) -> str:
        return "、".join(item for item in self.research_list if item)

    @property
    def tutor_label(self) -> str:
        bits = []
        if self.doctoral_tutor:
            bits.append("博导")
        if self.master_tutor:
            bits.append("硕导")
        return " · ".join(bits)

    @property
    def has_standard_homepage(self) -> bool:
        return is_standard_homepage(self.url)

    def basics(self) -> list[tuple[str, str]]:
        phone = " / ".join(part for part in (self.phone, self.mobile) if part)
        rows = (
            ("学科", self.discipline),
            ("学位", self.degree),
            ("学历", self.education),
            ("毕业院校", self.graduated),
            ("职务", self.job),
            ("办公地点", self.office),
            ("邮箱", self.email),
            ("联系方式", self.contact),
            ("电话", phone),
            ("通讯地址", self.address),
            ("入职时间", self.entry_time),
        )
        return [(label, value) for label, value in rows if value]


class Faculty:
    SEARCH_PAGE = f"{FACULTY_HOST}/search.jsp?urltype=tree.TreeTempUrl&wbtreeid=1041"
    SEARCH_API = f"{FACULTY_HOST}/system/resource/tsites/advancesearch.jsp"
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def _headers(self, referer: str) -> dict[str, str]:
        return {
            "User-Agent": self.UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Referer": referer,
        }

    def load_filters(self) -> FacultyFilter:
        response = self.session.get(
            self.SEARCH_PAGE,
            headers=self._headers(f"{FACULTY_HOST}/index.jsp"),
            timeout=20,
        )
        response.raise_for_status()
        colleges = parse_filter_options(response.text, "selectByCollege")
        disciplines = parse_filter_options(response.text, "selectByDiscipline")
        return FacultyFilter(
            colleges=[(option_id, name) for option_id, name, _depth in colleges if option_id != "0"],
            disciplines=[(option_id, name) for option_id, name, _depth in disciplines if option_id != "0"],
        )

    def search(
            self,
            teacher_name: str = "",
            college_id: str = "0",
            discipline_id: str = "0",
            page: int = 1,
            page_size: int = 20) -> tuple[int, list[FacultyMember]]:
        response = self.session.get(
            self.SEARCH_API,
            params={
                "pageindex": page,
                "pagesize": min(page_size, 100),
                "profilelen": 400,
                "collegeid": college_id or "0",
                "disciplineid": discipline_id or "0",
                "enrollid": "0",
                "honorid": "0",
                "teacherName": teacher_name,
                "searchDirection": "",
                "py": "",
                "rankid": "0",
                "degreeid": "0",
                "tutorType": "",
                "viewmode": "8",
                "viewid": "1095235",
                "siteOwner": "2105667170",
                "viewUniqueId": "1095235",
                "showlang": "zh_CN",
                "ispreview": "false",
                "basenum": "0",
                "productType": "0",
                "ellipsis": "...",
                "alignright": "false",
            },
            headers=self._headers(self.SEARCH_PAGE),
            timeout=20,
        )
        if not looks_like_json(response.text):
            raise ServerError(1, "教师检索接口返回异常（非 JSON 响应）")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServerError(1, "教师主页接口返回了无法解析的数据") from exc
        members = [_parse_member(item) for item in payload.get("teacherData") or []]
        return int(payload.get("totalnum") or len(members)), members

    def fetch_homepage(self, url: str) -> HomepageResult:
        if not url:
            return HomepageResult.not_standard(url)
        if not is_standard_homepage(url):
            return HomepageResult.not_standard(url)
        try:
            response = self.session.get(
                url,
                headers=self._headers(self.SEARCH_PAGE),
                timeout=20,
            )
            html = decode_page(response.content)
        except requests.RequestException as exc:
            return HomepageResult.error(str(exc) or "主页加载失败")
        if is_unavailable_page(html):
            return HomepageResult.unavailable()
        try:
            return HomepageResult.success(parse_homepage(html, url), url)
        except Exception as exc:
            return HomepageResult.error(str(exc) or "主页解析失败")


def _parse_member(item: dict) -> FacultyMember:
    directions = item.get("researchDirectionList") or []
    research = [
        str(one.get("researchDirectionTitle") or "").strip()
        for one in directions if one
    ]
    return FacultyMember(
        teacher_id=str(item.get("teacherId") or ""),
        name=str(item.get("name") or ""),
        english_name=str(item.get("ename") or "").strip(),
        college=str(item.get("collegeName") or item.get("unit") or "").strip(),
        rank=str(item.get("prorank") or "").strip(),
        job=str(item.get("job") or "").strip(),
        discipline=str(item.get("discipline") or "").strip(),
        degree=str(item.get("degree") or "").strip(),
        education=str(item.get("education") or "").strip(),
        graduated=str(item.get("graduatedUniversity") or "").strip(),
        url=str(item.get("url") or "").strip(),
        email=str(item.get("email") or "").strip(),
        contact=str(item.get("contact") or "").strip(),
        phone=str(item.get("phone") or "").strip(),
        mobile=str(item.get("mobilephone") or "").strip(),
        office=str(item.get("officeLocation") or "").strip(),
        address=str(item.get("address") or "").strip(),
        entry_time=str(item.get("entryTime") or "").strip(),
        profile=str(item.get("profile") or item.get("profileSummary") or "").strip(),
        research_list=[item for item in research if item],
        doctoral_tutor=item.get("doctorTutor") == 1,
        master_tutor=item.get("gtutor") == 1,
        pic_url=absolute_url(str(item.get("picUrl") or "").strip(), FACULTY_HOST),
    )
