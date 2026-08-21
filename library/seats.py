from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from html import unescape as html_unescape
from typing import Any

import requests
from lxml import html as lxml_html

logger = logging.getLogger("default")


BASE_URL = "http://rg.lib.xjtu.edu.cn:8086"
# 座位号：字母 + 2~4 位数字（如 A101、D004）；前后不得再跟字母数字，避免误匹配文本中的数字。
SEAT_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{2,4}(?![0-9])")
# showConfirmModal(message, action, id) 第二、三个参数。
# 格式写死为真实页面形态（单引号、无空格）：showConfirmModal('确认您已到馆?', 'ruguan1', '4953117')
# 实体由 html.unescape 提前解码；若服务器改版（引号/空格/参数顺序变化），此处需同步。
CONFIRM_RE = re.compile(r"showConfirmModal\('[^']*', '(\w+)', '(\d+)'\)")

# 预约动作：页面 JS 的 action 参数 → 展示名（与前端源码 switch(currentAction) 一致）
ACTION_LABELS = {
    "cancel": "取消预约",
    "ruguan1": "入馆签到",
    "leave": "中途离开",
    "return": "中途返回",
}
# 展示名 → 动作 URL 参数（/my/?{参数}=1&ri={id}）。
# 注意：页面 action 名与 URL 参数名不同（ruguan1→firstruguan、leave→midleave、
# return→midreturn），来源为前端源码 switch(currentAction) 的 url 赋值，不得由上面推导。
ACTION_PARAMS = {
    "取消预约": "cancel",
    "入馆签到": "firstruguan",
    "中途离开": "midleave",
    "中途返回": "midreturn",
}

# 页面中出现任一 token 即存在其它预约（预约失败的典型原因）
ALREADY_BOOKED_TOKENS = ("已有预约", "已预约", "换座", "已经预约", "存在预约")
NO_BOOKING_TOKENS = ("暂无预约", "没有预约", "无预约")

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
    booking: MyBooking | None = None


@dataclass
class MyBooking:
    seat_id: str
    area: str
    status_text: str
    action_urls: dict[str, str] = field(default_factory=dict)


class Library:
    """图书馆座位系统客户端。session 需为已登录的共享会话（登录态由调用方保证）。"""

    def __init__(self, session: requests.Session):
        self.session = session
        self.area_stats: dict[str, AreaStats] = {}

    # ---- 请求封装 ----

    def _get(self, url: str, ajax: bool = False, timeout: int = 15) -> requests.Response:
        headers = {}
        if ajax:
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        return self.session.get(url, headers=headers, timeout=timeout)

    def _parse_json(self, body: str) -> dict[str, Any]:
        if not (body.lstrip().startswith("{") or body.lstrip().startswith("[")):
            raise RuntimeError("图书馆接口返回异常（非 JSON 响应）")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("图书馆接口返回了无法解析的数据") from exc

    @staticmethod
    def _parse_scount(scount: Any) -> dict[str, AreaStats]:
        """scount: {区域码: [总数, 空闲]} → 统计；字段缺失/类型不符则跳过（UI 不显示统计即可）。"""
        result: dict[str, AreaStats] = {}
        for key, value in (scount or {}).items():
            if key not in AREA_MAP.values() or not isinstance(value, list) or len(value) < 2:
                continue
            try:
                result[key] = AreaStats(available=int(value[1]), total=int(value[0]))
            except (TypeError, ValueError):
                continue
        return result

    # ---- 动作一：查询座位状态 ----

    def get_seats(self, area_code: str) -> tuple[list[SeatInfo], dict[str, AreaStats]]:
        response = self._get(f"{BASE_URL}/qseat?sp={area_code}", ajax=True)
        payload = self._parse_json(response.text)
        stats = self._parse_scount(payload.get("scount"))
        if stats:
            self.area_stats = stats
        seats = [
            SeatInfo(seat_id=seat_id, available=int(status) == 0)
            for seat_id, status in (payload.get("seat") or {}).items()
        ]
        seats.sort(key=lambda item: (item.seat_id[:1], item.seat_id))
        return seats, self.area_stats

    # ---- 动作二：选座位 ----

    def book_seat(self, seat_id: str, area_code: str) -> BookResult:
        """预约目标座位；若已有其它预约则自动换成目标座位。"""
        response = self._get(f"{BASE_URL}/seat/?kid={seat_id}&sp={area_code}")
        logger.info("book_seat: seat=%s area=%s landed=%s len=%s", seat_id, area_code, response.url, len(response.text))
        if self._is_my_page(response.url):
            booking = self._booking_from_html(response.text, response.url)
            return BookResult(True, f"座位 {seat_id} 预约成功", response.url, booking=booking)
        body_text = self._body_text(response.text)
        if any(token in body_text for token in ALREADY_BOOKED_TOKENS):
            return self._swap_seat(seat_id, area_code)
        return BookResult(False, self._failure_reason(body_text), response.url)

    def _swap_seat(self, seat_id: str, area_code: str) -> BookResult:
        """把当前预约换到目标座位，以 /my/ 复查座位号严格一致确认。"""
        response = self._get(f"{BASE_URL}/updateseat/?kid={seat_id}&sp={area_code}")
        booking = self.get_my_booking()
        booked = booking.seat_id if booking else ""
        if booked and booked.lower() == seat_id.lower():
            return BookResult(True, f"已换座到 {booked}", response.url, booking=booking)
        return BookResult(False, f"换座未生效{f'（当前仍为 {booked}）' if booked else ''}", response.url)

    def _is_my_page(self, url: str) -> bool:
        candidates = [url]
        try:
            from auth import getOrdinaryUrl
            ordinary = getOrdinaryUrl(url)
            if ordinary:
                candidates.append(ordinary)
        except Exception:
            pass
        return any("/my/" in item or "/seat/my" in item for item in candidates)

    # ---- 动作三：当前预约 ----

    def get_my_booking(self) -> MyBooking | None:
        response = self._get(f"{BASE_URL}/my/", timeout=12)
        logger.info("get_my_booking: %s len=%s", response.url, len(response.text))
        return self._booking_from_html(response.text, response.url)

    # ---- 预约页解析 ----

    def _booking_from_html(self, html: str, url: str = "") -> MyBooking | None:
        body_text = self._body_text(html)
        if any(token in body_text for token in NO_BOOKING_TOKENS):
            return None
        seat = SEAT_ID_RE.search(body_text)
        if not seat:
            return None
        status = re.search(r"预约状态[:：]\s*(\S+)", body_text)
        area = next((name for name in AREA_MAP if name in body_text), "")
        reserve_id, actions_present = self._reserve_id_and_actions(html, url)
        actions = self._build_actions(reserve_id, actions_present)
        booking = MyBooking(seat.group(0), area, status.group(1) if status else "", actions)
        logger.info(
            "get_my_booking: seat=%s area=%s status=%s actions=%s",
            booking.seat_id, booking.area, booking.status_text, list(actions),
        )
        return booking

    def _reserve_id_and_actions(self, html: str, url: str) -> tuple[str, set[str]]:
        """提取 (reserve_id, 页面当前渲染的动作)。

        reserve_id 是动作 URL 的唯一动态参数（showConfirmModal 的第三个参数）；
        页面按预约状态只渲染当前可执行的按钮（如未入馆时无“中途离开”），
        动作集合来自页面实际出现的 showConfirmModal action 参数。
        """
        normalized = html_unescape(html)
        present: set[str] = set()
        reserve_id = ""
        for action, ri in CONFIRM_RE.findall(normalized):
            label = ACTION_LABELS.get(action)
            if label:
                present.add(label)
            if not reserve_id:
                reserve_id = ri
        if not reserve_id:
            match = re.search(r"[?&]ri=(\d+)", url)
            if match:
                reserve_id = match.group(1)
        return reserve_id, present

    def _build_actions(self, reserve_id: str, actions_present: set[str]) -> dict[str, str]:
        if not reserve_id or not actions_present:
            return {}
        return {
            label: f"{BASE_URL}/my/?{param}=1&ri={reserve_id}"
            for label, param in ACTION_PARAMS.items()
            if label in actions_present
        }

    @staticmethod
    def _body_text(html: str) -> str:
        try:
            return lxml_html.fromstring(html).text_content()
        except Exception:
            return html

    # ---- 动作执行 ----

    def execute_action(self, url: str) -> BookResult:
        response = self._get(url)
        if "cancel=1" in url:
            booking = self.get_my_booking()
            if booking is None:
                return BookResult(True, "已取消预约", response.url)
            return BookResult(False, f"取消未生效，当前仍为 {booking.seat_id}", response.url)
        # 签到/离开/返回不声明状态断言（页面文案可能变化），如实告知，UI 刷新展示真实结果。
        return BookResult(True, "操作已提交，稍后自动刷新最新状态", response.url)

    # ---- 失败原因 ----

    def _failure_reason(self, body_text: str) -> str:
        if "30分钟" in body_text:
            return "30 分钟内不能重复预约"
        if "已被预约" in body_text or "已被占" in body_text:
            return "该座位已被他人预约"
        if any(token in body_text for token in ALREADY_BOOKED_TOKENS):
            return "您已有其他座位预约"
        if "不在预约时间" in body_text or "未开放" in body_text:
            return "当前不在预约开放时间"
        if "维护" in body_text:
            return "系统维护中"
        return "预约失败"
