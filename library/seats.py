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

# 校区 ID 与展示名（ID 由学校系统定义：east=兴庆、inno=创新港、west=雁塔）。
CAMPUSES = {
    "east": "兴庆",
    "inno": "创新港",
    "west": "雁塔",
}
# 楼层码前缀 → 校区名（楼层码真实命名，来自 /seatui floor-selector 实测：
# 兴庆=xingqing*floor、创新港=inno*floor、雁塔=yanta*floor）
FLOOR_PREFIX_CAMPUS = {
    "xingqing": "兴庆",
    "inno": "创新港",
    "yanta": "雁塔",
}
# 楼层码前缀 → 校区 ID（切换 rplace 用）
PREFIX_CAMPUS_ID = {"xingqing": "east", "inno": "inno", "yanta": "west"}
# 各校区的真实楼层码（floor-selector 渲染值，楼层数也随之固定），按层数升序
CAMPUS_FLOORS = {
    "east": ["xingqing2floor", "xingqing3floor", "xingqing4floor"],
    "inno": ["inno1floor", "inno2floor"],
    "west": ["yanta1floor", "yanta2floor", "yanta3floor", "yanta4floor"],
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
            if not key or not isinstance(value, list) or len(value) < 2:
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

    def get_seat_layout(self, area_code: str) -> tuple[dict[str, tuple[float, ...]], dict[str, int]]:
        """可视化选座：座位/区域平面布局 + 实时状态。

        返回 (positions, status)：positions 为 {键: (left, top, width, height)}
        （来自 /qseatuist，图上的矩形）；status 为 {键: 状态码}，
        2=空闲可点，0/1/3/-1=占用/使用中/离开/取消；
        特殊键 ``cancel``（status=-2）是图上的“返回上一级”按钮矩形。
        """
        response = self._get(f"{BASE_URL}/qseatuist?sp={area_code}", ajax=True)
        return self._parse_layout_payload(self._parse_json(response.text))

    @staticmethod
    def _parse_layout_payload(payload: dict) -> tuple[dict[str, tuple[float, ...]], dict[str, int]]:
        positions: dict[str, tuple[float, ...]] = {}
        status: dict[str, int] = {}
        for seat_id, value in payload.items():
            if seat_id in ("", "spacecancel") or not isinstance(value, list) or len(value) < 4:
                continue
            try:
                positions[seat_id] = tuple(float(v) for v in value[:4])
                if len(value) >= 5:
                    status[seat_id] = int(value[4])
            except (TypeError, ValueError):
                continue
        return positions, status

    def get_area_names(self, floor_code: str) -> dict[str, str]:
        """楼层区域码 → 中文名（来源：qspace 的 sp 字段，跟随账号当前校区）。

        与前端列表查询（yCheck → /qspace?floor=）同源；一次请求拿整层区域名。
        """
        try:
            response = self._get(f"{BASE_URL}/qspace?lang=zh&floor={floor_code}", ajax=True)
            payload = self._parse_json(response.text)
        except RuntimeError:
            return {}
        return {key: name for key, name in (payload.get("sp") or {}).items() if key}

    def get_current_campus(self) -> str:
        """当前账号校区 ID（/modify 页 rplace 的选中值），为空表示未知。"""
        try:
            html = self._get(f"{BASE_URL}/modify", timeout=20).text
        except requests.RequestException as exc:
            logger.debug("get_current_campus: %s", exc)
            return ""
        match = re.search(r'<option[^>]*selected[^>]*value="([^"]+)"', html)
        return match.group(1) if match else ""

    def switch_campus(self, campus: str) -> bool:
        """切换账号校区（POST /modify 的 rplace），返回是否提交成功。

        调用方负责用完切回原校区（rplace 是账号级个人信息）。
        """
        try:
            html = self._get(f"{BASE_URL}/modify", timeout=20).text
        except requests.RequestException as exc:
            logger.debug("switch_campus: %s", exc)
            return False
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        email = re.search(r'id="email"[^>]*value="([^"]*)"', html)
        tel = re.search(r'id="tel"[^>]*value="([^"]*)"', html)
        if not (csrf and email and tel):
            return False
        try:
            self.session.post(
                f"{BASE_URL}/modify",
                data={
                    "csrf_token": csrf.group(1),
                    "email": email.group(1),
                    "tel": tel.group(1),
                    "rplace": campus,
                    "subit": "确认",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            logger.debug("switch_campus post: %s", exc)
            return False
        return True

    def get_floor_image(self, code: str) -> bytes | None:
        """平面图 JPG 字节（/static/images/ui10/{code}.jpg），楼层/区域通用。

        下载失败返回 None，由界面降级为无底图渲染。
        """
        try:
            response = self._get(f"{BASE_URL}/static/images/ui10/{code}.jpg", timeout=20)
            if response.ok and response.content:
                return response.content
        except requests.RequestException as exc:
            logger.debug("get_floor_image: %s", exc)
        return None

    def get_floor_images(self, area_code: str) -> dict[str, bytes | None]:
        """区域平面图各状态的瓦片图（/static/images/ui10/）。

        返回 {状态键: 字节}：base=原图、book=已预约、inside=使用中、
        leave=中途离开、blanket=取消（全局一张）。任一失败为 None，界面降级。
        """
        variants = {
            "base": f"{area_code}.jpg",
            "book": f"{area_code}-book.jpg",
            "inside": f"{area_code}-inside.jpg",
            "leave": f"{area_code}-leave.jpg",
            "blanket": "blanket.jpg",
        }
        result: dict[str, bytes | None] = {}
        for key, filename in variants.items():
            try:
                response = self._get(f"{BASE_URL}/static/images/ui10/{filename}", timeout=20)
                result[key] = response.content if response.ok else None
            except requests.RequestException as exc:
                logger.debug("get_floor_images %s: %s", filename, exc)
                result[key] = None
        return result

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
        """从 /my/ 页解析当前有效预约。

        页面结构固定置：
        - 当前预约 = 第一张 bs-calltoaction 卡片（历史卡在其后）
        - 座位行 = 卡内第 1 个 <hr> 的 tail（``区域名&nbsp;座位号``）
        - 状态 = cta-button 内第 1 个无 class 的 h3
        无当前预约时第一张卡不含“取消预约”按钮（纯历史页），返回 None。
        """
        try:
            tree = lxml_html.fromstring(html)
        except Exception:
            return None
        cards = tree.xpath("//div[contains(@class, 'bs-calltoaction')]")
        if not cards:
            return None
        card = cards[0]
        # 当前可操作预约才有“取消预约”按钮；纯历史页第一张卡无（结构特征，非文本筛选）
        if not card.xpath(".//a[contains(text(), '取消预约')]"):
            return None
        hrs = card.xpath(".//hr")
        if not hrs or not (hrs[0].tail or "").strip():
            return None
        tail = hrs[0].tail.strip()
        if "\xa0" not in tail:  # 座位行固定为 “区域名&nbsp;座位号”，异常结构归为无预约
            return None
        area, seat = tail.rsplit("\xa0", 1)
        area, seat = area.strip(), seat.strip()
        status_nodes = card.xpath(
            ".//div[contains(@class, 'cta-button')]//h3[not(@class)]")
        status_text = status_nodes[0].text_content().strip() if status_nodes else ""
        reserve_id, actions_present = self._reserve_id_and_actions(html, url)
        booking = MyBooking(
            seat, area, status_text,
            self._build_actions(reserve_id, actions_present))
        logger.info(
            "get_my_booking: seat=%s area=%s status=%s actions=%s",
            booking.seat_id, booking.area, booking.status_text,
            list(booking.action_urls))
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
