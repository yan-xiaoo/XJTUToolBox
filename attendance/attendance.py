from __future__ import annotations

import datetime
import math
from enum import Enum
from urllib.parse import parse_qs, urlparse

from auth import ATTENDANCE_URL, ATTENDANCE_WEBVPN_URL, POSTGRADUATE_ATTENDANCE_URL, POSTGRADUATE_ATTENDANCE_WEBVPN_URL, ServerError
from auth.new_login import NewLogin, NewWebVPNLogin
from auth.new_qrcode_login import QRCodeLoginMixin
from schedule.schedule_service import ScheduleService


def attendance_domain(is_postgraduate: bool) -> str:
    """
    本科与研究生考勤系统接口完全一致，但部署在不同域名下。
    :param is_postgraduate: 是否为研究生
    """
    return "yjs-kq.xjtu.edu.cn" if is_postgraduate else "bk-kq.xjtu.edu.cn"


class FlowRecordType(Enum):
    """考勤流水的状态。新版考勤系统只区分“有效流水”与“未匹配”。"""
    INVALID = 0  # 无效：刷卡时不在任何课程的考勤范围内
    VALID = 1  # 有效：刷卡时间落在某门课程的考勤范围内
    UNKNOWN = 9  # 未知：本地缓存中的状态无法识别


class WaterType(Enum):
    """课程的考勤状态"""
    NORMAL = 1  # 正常
    LATE = 2  # 迟到
    ABSENCE = 3  # 缺勤
    LEAVE = 5  # 请假
    PENDING = 6  # 待考勤：该课次尚未产生考勤结果
    NOT_REQUIRED = 7  # 不考勤：该课次无需考勤
    UNKNOWN = 9  # 未知：服务端返回了未识别的状态


# 新版考勤系统返回的考勤状态字符串，取值与前端状态标签一致
_ATTENDANCE_STATUS = {
    "PENDING": WaterType.PENDING,
    "NORMAL": WaterType.NORMAL,
    "LATE": WaterType.LATE,
    "ABSENT": WaterType.ABSENCE,
    "LEAVE": WaterType.LEAVE,
    "NOT_REQUIRED": WaterType.NOT_REQUIRED,
}

# 学期名称到学期编号后缀的映射
_SEMESTER_ORDINALS = {
    "第一学期": 1,
    "第二学期": 2,
    "第三学期": 3,
    "第四学期": 4,
}


class AttendanceFlow:
    """一次刷卡流水"""
    def __init__(self, sbh: str, place: str, water_time: str, type_: FlowRecordType):
        """
        创建一个考勤记录信息
        :param sbh: 此考勤信息的编号
        :param place: 打卡的地点（教室）
        :param water_time: 打卡的时间
        :param type_: 打卡类型，有效/无效
        """
        self.sbh = sbh
        self.place = place
        self.water_time = water_time
        self.type_ = type_

    def __repr__(self):
        return f"{self.__class__.__name__}(sbh={self.sbh}, place={self.place}, water_time={self.water_time}, type_={self.type_})"

    @classmethod
    def from_json(cls, json):
        """从本地缓存中恢复一条考勤流水"""
        try:
            type_ = FlowRecordType(int(json["isdone"]))
        except ValueError:
            type_ = FlowRecordType.UNKNOWN
        return cls(json["sBh"], json["eqno"], json["watertime"], type_)

    @classmethod
    def from_response_json(cls, json):
        """从考勤系统的流水接口返回中创建一条考勤流水"""
        return cls(json["id"], json["classroomName"], json["collectTime"],
                   FlowRecordType.VALID if json["effective"] else FlowRecordType.INVALID)

    def json(self):
        return {"sBh": self.sbh, "eqno": self.place, "watertime": self.water_time, "isdone": self.type_.value}


class AttendanceWaterRecord:
    """一条课程考勤记录"""
    def __init__(self, sbh: str, term_string: str, start_time: int, end_time: int, week: int, location: str, teacher: str, status: WaterType, date: datetime.date):
        """
        创建一个考勤流水信息
        :param sbh: 此考勤信息的编号
        :param term_string: 学期字符串，如 "2026-2027-1"
        :param start_time: 开始节次
        :param end_time: 结束节次
        :param week: 周数
        :param location: 地点
        :param teacher: 教师
        :param status: 状态
        :param date: 上课日期
        """
        self.sbh = sbh
        self.term_string = term_string
        self.start_time = start_time
        self.end_time = end_time
        self.week = week
        self.location = location
        self.teacher = teacher
        self.status = status
        self.date = date

    def __repr__(self):
        return f"{self.__class__.__name__}(sbh={self.sbh}, term_string={self.term_string}, start_time={self.start_time}, end_time={self.end_time}, week={self.week}, location={self.location}, teacher={self.teacher}, status={self.status}, date={self.date})"

    @classmethod
    def from_response_json(cls, json, term_string: str):
        """从考勤系统的考勤记录接口返回中创建一条考勤记录"""
        return cls(str(json["resultId"]), term_string, json["startSection"], json["endSection"], json["courseWeek"],
                   json["classroomName"], json["teacherName"],
                   _ATTENDANCE_STATUS.get(json["attendanceStatus"], WaterType.UNKNOWN),
                   datetime.datetime.strptime(json["attendanceDate"], "%Y-%m-%d").date())


class _AttendanceTokenMixin:
    """
    新版考勤系统在完成统一认证后，还需要用回调 URL 中的 loginRequestId 与 ticket
    向 /sa/auth/cas/exchange 换取业务 token，并在后续请求中携带 X-Business-Token header。
    """
    is_postgraduate: bool

    def postLogin(self, login_response) -> None:
        query = parse_qs(urlparse(login_response.url).query)
        response = self._post(
            f"https://{attendance_domain(self.is_postgraduate)}/sa/auth/cas/exchange",
            json={"loginRequestId": query["loginRequestId"][0], "ticket": query["ticket"][0]},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        result = response.json()
        if result["code"] != 0:
            raise ServerError(result["code"], result["message"])
        self.session.headers.update({"X-Business-Token": result["data"]["tokenValue"]})


class AttendanceNewLogin(_AttendanceTokenMixin, NewLogin):
    """通过统一身份认证登录考勤系统。"""

    def __init__(self, session=None, is_postgraduate=False, visitor_id=None):
        super().__init__(POSTGRADUATE_ATTENDANCE_URL if is_postgraduate else ATTENDANCE_URL, session, visitor_id=visitor_id)
        self.is_postgraduate = is_postgraduate


class AttendanceNewWebVPNLogin(_AttendanceTokenMixin, NewWebVPNLogin):
    """通过 WebVPN 登录考勤系统。"""

    def __init__(self, session=None, is_postgraduate=False, visitor_id=None):
        super().__init__(POSTGRADUATE_ATTENDANCE_WEBVPN_URL if is_postgraduate else ATTENDANCE_WEBVPN_URL, session=session,
                         visitor_id=visitor_id)
        self.is_postgraduate = is_postgraduate


class AttendanceNewQRCodeLogin(QRCodeLoginMixin, AttendanceNewLogin):
    """使用二维码登录考勤系统。"""

    def __init__(self, session: object | None = None, is_postgraduate: bool = False,
                 visitor_id: str | None = None) -> None:
        super().__init__(session=session, is_postgraduate=is_postgraduate, visitor_id=visitor_id)


class AttendanceNewWebVPNQRCodeLogin(QRCodeLoginMixin, AttendanceNewWebVPNLogin):
    """通过 WebVPN 使用二维码登录考勤系统。"""

    def __init__(self, session: object | None = None, is_postgraduate: bool = False,
                 visitor_id: str | None = None) -> None:
        super().__init__(session=session, is_postgraduate=is_postgraduate, visitor_id=visitor_id)


class Attendance:
    """
    此类封装了一系列考勤系统接口，可以用来查询考勤信息等。
    请注意：考勤系统对同一个 session 的连接存在时间限制。因此，不要持久性的存储此类的对象；每次使用时通过 AttendanceNewLogin 或
    AttendanceNewWebVPNLogin 重新得到一个登录的 session，然后重新创建此对象。
    """
    def __init__(self, session, is_postgraduate=False, timeout=15):
        """
        创建一个接口对象
        :param session: 已经登录考勤系统的 session 对象
        :param is_postgraduate: 是否为研究生。true：是；false：不是（本科生）
        本科生和研究生的网站接口完全一致，但是二者不在同一域名下（bk-kq.xjtu.edu.cn 和 yjs-kq.xjtu.edu.cn）。此参数将用于决定访问哪个系统。
        :param timeout: 单次请求的超时时间，单位为秒
        """
        self.session = session
        # 缓存学期列表
        self._semesters = None
        # 是否为研究生
        self.is_postgraduate = is_postgraduate
        # 单次请求的超时时间
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs):
        """
        向考勤系统发起请求并返回响应中的 data 字段。
        :raise ServerError: 如果服务器返回了非 0 的业务错误码
        """
        url = f"https://{attendance_domain(self.is_postgraduate)}/sa{path}"
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        result = response.json()
        if result["code"] != 0:
            raise ServerError(result["code"], result["message"])
        return result["data"]

    def _get(self, path: str, **kwargs):
        """发起 GET 请求并返回 data 字段"""
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs):
        """发起 POST 请求并返回 data 字段"""
        return self._request("POST", path, **kwargs)

    @property
    def semesters(self) -> list:
        """获得所有学期的列表，第一个元素为当前学期，尽可能返回缓存的内容"""
        if self._semesters is None:
            self._semesters = self._get("/student/service/timetable/semesters")
        return self._semesters

    @staticmethod
    def _term_name(semester: dict) -> str:
        """把学期信息转换为学期编号，如 "2026-2027-1" """
        return f"{semester['academicYear']}-{_SEMESTER_ORDINALS[semester['semesterName']]}"

    def _find_semester(self, term_name: str = None) -> dict:
        """根据学期编号查找学期，term_name 为空时返回当前学期"""
        if term_name is None:
            return self.semesters[0]
        for semester in self.semesters:
            if self._term_name(semester) == term_name:
                return semester
        raise ValueError(f"未找到学期 {term_name}")

    def getNearTerm(self) -> dict:
        """
        获得当前学期的信息。返回的字典包含学期编号（name）、学期编号 ID（semesterId）、
        学期开始日期（startDate）、学期结束日期（endDate）等字段。
        """
        semester = self.semesters[0]
        return {**semester, "name": self._term_name(semester)}

    def getScheduleLessons(self, term_name: str = None) -> list:
        """
        获取整学期课表，返回与 jwxt 兼容的课程 dict 列表。
        每个 dict 包含 KCM/SKJS/JASMC/SKXQ/KSJC/JSJC/SKZC/XNXQDM 字段，
        可直接用于 schedule_service.getCourseGroupFromJson。

        :param term_name: 学期编号，如 '2026-2027-1'。None 表示当前学期。
        :return: 课程 dict 列表
        """
        semester = self._find_semester(term_name)
        courses = self._get("/student/service/timetable/weekly",
                            params={"semesterId": semester["semesterId"]})["courses"]

        # 同一门课程可能分多段周次返回，按上课时间合并周次
        groups = {}
        for course in courses:
            key = (course["courseName"], course["teacherName"], course["classroomName"],
                   course["dayOfWeek"], course["startSection"], course["endSection"])
            groups.setdefault(key, set()).update(ScheduleService.parse_weeks_string(course["weekRanges"]))

        lessons = []
        for (name, teacher, location, day, start_time, end_time), weeks in groups.items():
            if not weeks:
                continue
            skzc = "".join("1" if week in weeks else "0" for week in range(1, max(weeks) + 1))
            lessons.append({
                "KCM": name,
                "SKJS": teacher,
                "JASMC": location,
                "SKXQ": str(day),
                "KSJC": str(start_time),
                "JSJC": str(end_time),
                "SKZC": skzc,
                "XNXQDM": self._term_name(semester),
            })
        return lessons

    def getFlowRecordWithPage(self, current=1, page_size=10) -> dict:
        """
        获得包含总页数、总数量、当前页数等信息的考勤流水信息
        :param current: 目前获取第几页
        :param page_size: 每页包含多少流水信息
        :return: 考勤流水信息的字典，其内容如下：
        - data: 考勤流水信息的列表
        - total_pages: 总页数
        - total_count: 总数量
        - current_page: 当前页数
        """
        data = self._post("/student/pc/attendance-streams/page",
                          json={"pageNum": current, "pageSize": page_size, "data": {}})
        return {
            "data": [AttendanceFlow.from_response_json(one) for one in data["rows"]],
            "total_pages": math.ceil(data["total"] / page_size),
            "total_count": data["total"],
            "current_page": current,
        }

    def getFlowRecordByTime(self, start_date: str, end_date: str = None) -> list:
        """
        根据时间段查询考勤流水信息。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式为 "%Y-%m-%d"。如果为 None，则默认为当前日期。
        """
        if end_date is None:
            end_date = datetime.date.today().isoformat()
        data = self._post("/student/pc/attendance-streams/page",
                          json={"pageNum": 1, "pageSize": 50,
                                "data": {"startDate": start_date, "endDate": end_date}})
        return [AttendanceFlow.from_response_json(one) for one in data["rows"]]

    def attendanceDetailByTime(self, start_date: str, end_date: str, current: int = 1, page_size: int = 10) -> list:
        """
        根据时间段查询课程考勤记录。
        :param start_date: 开始日期，格式为 "%Y-%m-%d"
        :param end_date: 结束日期，格式为 "%Y-%m-%d"
        :param current: 当前页数
        :param page_size: 每页的数量
        :return: 考勤记录（AttendanceWaterRecord）列表
        """
        data = self._post("/student/pc/attendance-records/page",
                          json={"pageNum": current, "pageSize": page_size,
                                "data": {"startDate": start_date, "endDate": end_date}})
        term_names = {semester["semesterId"]: self._term_name(semester) for semester in self.semesters}
        return [AttendanceWaterRecord.from_response_json(one, term_names[one["semesterId"]])
                for one in data["rows"]]
