from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from lxml import html as lxml_html

from auth.constant import MOBILE_BROWSER_UA


BASE_URL = "http://rg.lib.xjtu.edu.cn:8086"
SEAT_ID_RE = re.compile(r"(?:[A-Z]\d{2,4}|\b\d{3}\b)")
CONFIRM_RE = re.compile(r"showConfirmModal\s*\(\s*['\"][^'\"]*['\"]\s*,\s*'(\w+)'\s*,\s*'(\d+)'\s*\)")
MOBILE_UA = MOBILE_BROWSER_UA
MOBILE_ONLY_HINT = "移动端模式"

AREA_MAP = {
    "北楼二层外文库（东）": "north2east",
    "二层连廊及流通大厅": "north2elian",
    "北楼二层外文库（西）": "north2west",
    "南楼二层大厅": "south2",
    "北楼三层ILibrary-B（西）": "west3B",
    "大屏辅学空间": "eastnorthda",
    "南楼三层中段": "south3middle",
    "北楼三层ILibrary-A（东）": "east3A",
    "北楼四层西侧": "north4west",
    "北楼四层中间": "north4middle",
    "北楼四层东侧": "north4east",
    "北楼四层西南侧": "north4southwest",
    "北楼四层东南侧": "north4southeast",
}
AREA_MAP_REVERSE = {code: name for name, code in AREA_MAP.items()}
FLOORS = {
    "二楼": ["北楼二层外文库（东）", "二层连廊及流通大厅", "北楼二层外文库（西）", "南楼二层大厅"],
    "三楼": ["北楼三层ILibrary-B（西）", "大屏辅学空间", "南楼三层中段", "北楼三层ILibrary-A（东）"],
    "四楼": ["北楼四层西侧", "北楼四层中间", "北楼四层东侧", "北楼四层西南侧", "北楼四层东南侧"],
}
FLOOR_CODES = {"二楼": "xingqing2floor", "三楼": "xingqing3floor", "四楼": "xingqing4floor"}
AREA_FLOOR_CODES = {
    AREA_MAP[area]: FLOOR_CODES[floor]
    for floor, areas in FLOORS.items()
    for area in areas
    if area in AREA_MAP
}
INACTIVE_STATUSES = {"已取消", "已完成", "已过期", "已失效", "已违约", "超时取消", "超时未入馆", "超时", "已离馆"}


@dataclass
class SeatInfo:
    seat_id: str
    available: bool


@dataclass
class AreaStats:
    available: int
    total: int


@dataclass
class BookResult:
    success: bool
    message: str
    final_url: str = ""


@dataclass
class MyBooking:
    seat_id: str
    area: str
    status_text: str
    action_urls: dict[str, str] = field(default_factory=dict)


class Library:
    def __init__(self, session: requests.Session):
        self.session = session
        self.area_stats: dict[str, AreaStats] = {}

    def _headers(self, referer: str = f"{BASE_URL}/seat/", ajax: bool = False) -> dict[str, str]:
        headers = {"User-Agent": MOBILE_UA, "Referer": referer}
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        return headers

    def _get(self, url: str, referer: str = f"{BASE_URL}/seat/", ajax: bool = False, timeout: int = 15) -> requests.Response:
        response = self.session.get(url, headers=self._headers(referer, ajax), timeout=timeout)
        if MOBILE_ONLY_HINT in response.text:
            raise RuntimeError("请浏览器调成移动端模式访问！")
        return response

    def _looks_like_json(self, body: str) -> bool:
        stripped = body.lstrip()
        return stripped.startswith("{") or stripped.startswith("[")

    def _is_login_page(self, body: str, url: str) -> bool:
        return (
            'id="loginForm"' in body
            or 'name="execution"' in body
            or "cas/login" in body
            or "login.xjtu.edu.cn" in url
        )

    def _parse_json(self, body: str) -> dict[str, Any]:
        if not self._looks_like_json(body):
            raise RuntimeError("图书馆接口返回异常（非 JSON 响应）")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("图书馆接口返回了无法解析的数据") from exc

    def _parse_stats(self, scount: dict | None) -> dict[str, AreaStats]:
        result = {}
        for key, value in (scount or {}).items():
            if key not in AREA_MAP.values() or not isinstance(value, list) or len(value) < 2:
                continue
            result[key] = AreaStats(available=int(value[1]), total=int(value[0]))
        return result

    def _load_floor(self, area_code: str) -> None:
        floor_code = AREA_FLOOR_CODES.get(area_code)
        if not floor_code:
            return
        response = self._get(f"{BASE_URL}/qspace?lang=zh&floor={floor_code}", ajax=True)
        payload = self._parse_json(response.text)
        self.area_stats = self._parse_stats(payload.get("scount"))

    def get_seats(self, area_code: str) -> tuple[list[SeatInfo], dict[str, AreaStats]]:
        self._load_floor(area_code)
        floor_code = AREA_FLOOR_CODES.get(area_code)
        referer = f"{BASE_URL}/qspace?lang=zh&floor={floor_code}" if floor_code else f"{BASE_URL}/seat/"
        response = self._get(f"{BASE_URL}/qseat?sp={area_code}", referer=referer, ajax=True)
        if self._is_login_page(response.text, response.url):
            raise RuntimeError("图书馆登录态已失效")
        payload = self._parse_json(response.text)
        stats = self._parse_stats(payload.get("scount"))
        if stats:
            self.area_stats = stats
        seats = [
            SeatInfo(seat_id=seat_id, available=status == 0)
            for seat_id, status in (payload.get("seat") or {}).items()
        ]
        seats.sort(key=lambda item: (item.seat_id[:1], item.seat_id))
        return seats, self.area_stats

    def book_seat(self, seat_id: str, area_code: str, auto_swap: bool = True) -> BookResult:
        response = self._get(f"{BASE_URL}/seat/?kid={seat_id}&sp={area_code}")
        if "/my/" in response.url or "/seat/my/" in response.url:
            return BookResult(True, f"座位 {seat_id} 预约成功", response.url)
        body_text = ""
        try:
            body_text = lxml_html.fromstring(response.text).text_content()
        except Exception:
            body_text = response.text
        if auto_swap and any(token in body_text for token in ("已有预约", "已预约", "换座", "已经预约", "存在预约")):
            return self.swap_seat(seat_id, area_code)
        return BookResult(False, self._failure_reason(body_text), response.url)

    def _preflight(self, path: str) -> None:
        self._get(f"{BASE_URL}/my/")
        if path != "/my/":
            self._get(f"{BASE_URL}{path}")
        access_mode = getattr(self.session, "access_mode", None)
        if access_mode is not None and getattr(access_mode, "value", "") == "webvpn":
            cookie_url = (
                "https://webvpn.xjtu.edu.cn/wengine-vpn/cookie"
                f"?method=get&host=rg.lib.xjtu.edu.cn&scheme=http&path={path}"
                f"&vpn_timestamp={int(time.time() * 1000)}"
            )
            self.session.get(cookie_url, timeout=10, _skip_webvpn_rewrite=True)

    def swap_seat(self, seat_id: str, area_code: str) -> BookResult:
        self._preflight("/updateseat/")
        try:
            self._get(f"{BASE_URL}/qseat?sp={area_code}", referer=f"{BASE_URL}/updateseat/", ajax=True)
        except Exception:
            pass
        response = self._get(
            f"{BASE_URL}/updateseat/?kid={seat_id}&sp={area_code}",
            referer=f"{BASE_URL}/updateseat/",
        )
        booking = self.get_my_booking()
        booked = booking.seat_id if booking else ""
        if booked and (booked.lower() == seat_id.lower() or seat_id in booked or booked in seat_id):
            return BookResult(True, f"已换座到 {booked}", response.url)
        return BookResult(False, f"换座未生效{f'（当前仍为 {booked}）' if booked else ''}", response.url)

    def get_my_booking(self) -> MyBooking | None:
        for url in (f"{BASE_URL}/my/", f"{BASE_URL}/seat/my/", f"{BASE_URL}/seat/my"):
            response = self._get(url, timeout=12)
            if len(response.text) < 50 or self._is_login_page(response.text, response.url):
                continue
            try:
                tree = lxml_html.fromstring(response.text)
                body_text = tree.text_content()
            except Exception:
                continue
            if "Not Found" in body_text and len(body_text) < 800:
                continue
            if any(token in body_text for token in ("暂无预约", "没有预约", "无预约", "暂无")) and not SEAT_ID_RE.search(body_text):
                return None
            booking = self._parse_booking(response.text, body_text)
            if booking:
                return booking
        return None

    def _parse_booking(self, html: str, body_text: str) -> MyBooking | None:
        status_matches = list(re.finditer(r"预约状态[:：]\s*(\S+)", body_text))
        action_urls = self._parse_actions(html)
        if not status_matches:
            seat = SEAT_ID_RE.search(body_text)
            if not seat:
                return None
            area = next((name for name in AREA_MAP if name in body_text), "")
            return MyBooking(seat.group(0), area, "", action_urls)
        start = 0
        for match in status_matches:
            status = match.group(1)
            block = body_text[start:match.end()]
            start = match.end()
            if status in INACTIVE_STATUSES:
                continue
            seats = list(SEAT_ID_RE.finditer(block))
            if not seats:
                continue
            area = next((name for name in AREA_MAP if name in block), "")
            return MyBooking(seats[-1].group(0), area, status, action_urls)
        return None

    def _parse_actions(self, html: str) -> dict[str, str]:
        actions = {}
        for action, reserve_id in CONFIRM_RE.findall(html):
            url = self._action_url(action, reserve_id)
            label = self._action_label(action)
            if url and label:
                actions[label] = url
        if "取消预约" in actions:
            return actions
        for match in re.finditer(
            r"""['"](/my/\?(?:cancel|firstruguan|midleave|midreturn)=1&ri=)(\d+)['"]""",
            html,
        ):
            prefix, reserve_id = match.groups()
            label = self._action_label(prefix)
            if label and label not in actions:
                actions[label] = f"{BASE_URL}{prefix}{reserve_id}"
        return actions

    def _action_label(self, action: str) -> str:
        text = action.lower()
        if "cancel" in text:
            return "取消预约"
        if "ruguan" in text or "firstruguan" in text:
            return "入馆签到"
        if "leave" in text:
            return "中途离开"
        if "return" in text:
            return "中途返回"
        return ""

    def _action_url(self, action: str, reserve_id: str) -> str:
        mapping = {
            "cancel": f"{BASE_URL}/my/?cancel=1&ri={reserve_id}",
            "ruguan1": f"{BASE_URL}/my/?firstruguan=1&ri={reserve_id}",
            "leave": f"{BASE_URL}/my/?midleave=1&ri={reserve_id}",
            "midleave": f"{BASE_URL}/my/?midleave=1&ri={reserve_id}",
            "return": f"{BASE_URL}/my/?midreturn=1&ri={reserve_id}",
            "midreturn": f"{BASE_URL}/my/?midreturn=1&ri={reserve_id}",
        }
        return mapping.get(action, "")

    def execute_action(self, url: str) -> BookResult:
        self._preflight("/my/")
        response = self._get(url, referer=f"{BASE_URL}/my/")
        if "cancel=1" in url:
            booking = self.get_my_booking()
            if booking is None:
                return BookResult(True, "已取消预约", response.url)
            return BookResult(False, f"取消未生效，当前仍为 {booking.seat_id}", response.url)
        return BookResult(True, "操作已提交", response.url)

    def _failure_reason(self, body_text: str) -> str:
        if "30分钟" in body_text:
            return "30 分钟内不能重复预约"
        if "已被预约" in body_text or "已被占" in body_text:
            return "该座位已被他人预约"
        if "已有预约" in body_text or "已预约" in body_text:
            return "您已有其他座位预约"
        if "不在预约时间" in body_text or "未开放" in body_text:
            return "当前不在预约开放时间"
        if "维护" in body_text:
            return "系统维护中"
        return "预约失败"
