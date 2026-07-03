"""体育场馆预约 API 封装。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup


class VenueInfo:
    """场馆基本信息。"""
    def __init__(self, venue_id: int, name: str, address: str = "", icon: str = ""):
        self.id = venue_id
        self.name = name
        self.address = address
        self.icon = icon

    def __repr__(self):
        return f"Venue({self.id}, {self.name})"


class AreaSlot:
    """单个时段/场地的可预订信息。"""
    def __init__(self, area_id: int, area_name: str, stock_id: int,
                 time_slot: str, price: float, date_str: str,
                 status: int = 1, all_count: int = 0, using_num: int = 0):
        self.area_id = area_id
        self.area_name = area_name
        self.stock_id = stock_id
        self.time_slot = time_slot
        self.price = price
        self.date = date_str
        self.status = status
        self.all_count = all_count
        self.using_num = using_num
        self.is_available = status == 1

    def __repr__(self):
        return f"Slot({self.area_name} {self.time_slot} ¥{self.price})"


class VenueUtil:
    """体育场馆 API 工具类。"""

    BASE_URL = "http://202.117.17.144:8071"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

    def __init__(self, session: requests.Session):
        self.session = session
        self._venue_cache: list[VenueInfo] = []

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """统一请求方法，自动附加 Referer 和 UA。"""
        url = f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Referer", f"{self.BASE_URL}/")
        headers.setdefault("User-Agent", self.UA)
        return self.session.request(method, url, headers=headers, timeout=30, **kwargs)

    def get_venues(self) -> list[VenueInfo]:
        """获取场馆列表。"""
        r = self._request("GET", "/product/index.html")
        r.raise_for_status()
        venues = []
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li"):
            a = li.select_one("a[href]")
            if not a:
                continue
            href = a.get("href", "")
            if "show.html?id=" not in href:
                continue
            try:
                vid = int(href.split("show.html?id=")[-1].split("&")[0])
            except (ValueError, IndexError):
                continue
            name_el = li.select_one("h5")
            name = name_el.text.strip() if name_el else f"场馆{vid}"
            addr_el = li.select_one(".address")
            address = addr_el.text.strip().replace("地址：", "").replace("地址:", "") if addr_el else ""
            # 场馆图标类型
            icon_el = li.select_one("i.icon")
            icon_classes = icon_el.get("class", []) if icon_el else []
            icon = next((c for c in icon_classes if c.startswith("icon-")), "")
            venues.append(VenueInfo(vid, name, address, icon))
        self._venue_cache = venues
        return venues

    def get_available_slots(self, service_id: int, date_str: str) -> list[AreaSlot]:
        """获取可预订时段。"""
        r = self._request("GET", "/product/findOkArea.html",
                          params={"s_date": date_str, "serviceid": str(service_id)})
        r.raise_for_status()
        return self._parse_slots(r.json(), date_str, str(service_id))

    def get_locked_slots(self, service_id: int, date_str: str) -> list[AreaSlot]:
        """获取已被锁定的时段。"""
        r = self._request("GET", "/product/findLockArea.html",
                          params={"s_date": date_str, "serviceid": str(service_id)})
        r.raise_for_status()
        return self._parse_slots(r.json(), date_str, str(service_id))

    @staticmethod
    def _parse_slots(data: dict, date_str: str, service_id: str) -> list[AreaSlot]:
        """解析时段 JSON。"""
        items = data.get("object", [])
        if not isinstance(items, list):
            return []
        slots = []
        for item in items:
            if not isinstance(item, dict):
                continue
            stock = item.get("stock", {})
            slots.append(AreaSlot(
                area_id=item.get("id", 0),
                area_name=item.get("sname", ""),
                stock_id=item.get("stockid", 0),
                time_slot=stock.get("time_no", ""),
                price=float(stock.get("price", 0)),
                date_str=date_str,
                status=int(stock.get("status", 0)),
                all_count=int(stock.get("all_count", 0)),
                using_num=int(stock.get("using_num", 0)),
            ))
        return slots

    def get_date_range(self, days: int = 7) -> list[str]:
        """获取可查询的日期范围。"""
        today = date.today()
        return [(today + timedelta(days=i)).isoformat() for i in range(days)]

    def get_venue_by_id(self, venue_id: int) -> Optional[VenueInfo]:
        """从缓存中按 ID 查找场馆。"""
        for v in self._venue_cache:
            if v.id == venue_id:
                return v
        return None
