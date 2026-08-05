"""体育场馆预约 API 封装。

基于 http://202.117.17.144:8080/web/ 的 JSON API。
"""

from __future__ import annotations

import json
import logging
import re

import requests

_log = logging.getLogger("default")


class VenueAPIError(Exception):
    """Venue API failure with a user-friendly message.

    Raised when the server returns an HTML notice page (e.g. "not in
    booking hours") instead of the expected JSON payload.
    """


class VenueInfo:
    """场馆基本信息。"""

    def __init__(self, venue_id: int, name: str, address: str = "",
                 icon: str = "", category: str = "", advanceday: int = 7,
                 advancenum: int = 8):
        self.id = int(venue_id)     # 服务端 JSON id 是字符串，转 int
        self.name = name
        self.address = address
        self.icon = icon            # CSS class: "icon icon-sports square x64"
        self.category = category    # G/X/C/J
        self.advanceday = int(advanceday)  # 提前预订天数
        self.advancenum = int(advancenum)  # 单次最多可订数量

    def __repr__(self) -> str:
        return f"Venue({self.id}, {self.name})"


class AreaSlot:
    """单个时段/场地的可预订信息。"""

    def __init__(self, area_id: int, area_name: str, stock_id: int,
                 time_slot: str, price: float, date_str: str,
                 status: int = 1, using_num: int = 0, all_count: int = 0):
        self.area_id = area_id       # findOkArea item.id
        self.area_name = area_name   # sname
        self.stock_id = stock_id     # findOkArea item.stockid
        self.time_slot = time_slot   # "18:30-19:30"
        self.price = price
        self.date = date_str
        self.status = status         # 1=可预订, 2=已预订/锁定
        self.using_num = using_num
        self.all_count = all_count
        self.is_available = status == 1

    def __repr__(self) -> str:
        return f"Slot({self.area_name} {self.time_slot} ¥{self.price})"


class OrderDetail:
    """单个订单明细（一场地一时段）。"""

    def __init__(self, date_str: str, time_slot: str, area_name: str,
                 price: float, service_id: str, service_name: str):
        self.date = date_str          # stock.s_date
        self.time_slot = time_slot    # stock.time_no
        self.area_name = area_name    # stockdetail.sname
        self.price = float(price)
        self.service_id = service_id  # serviceid
        self.service_name = service_name  # service.name

    def __repr__(self) -> str:
        return f"OrderDetail({self.date} {self.time_slot} {self.area_name})"


class OrderInfo:
    """订单信息（从 searchorder API 解析）。"""

    STATUS_TEXT = {0: "预订中", 1: "预订成功", 2: "预订取消"}

    def __init__(self, orderid: str, status: int, createdate: str,
                 price: float, details: list[OrderDetail]):
        self.orderid = str(orderid)
        self.status = int(status)
        self.createdate = createdate  # "2026-08-03 21:34:43"
        self.price = float(price)
        self.details = details

    @property
    def status_text(self) -> str:
        return self.STATUS_TEXT.get(self.status, f"未知({self.status})")

    @property
    def venue_name(self) -> str:
        return self.details[0].service_name if self.details else ""

    def __repr__(self) -> str:
        return f"Order({self.orderid}, {self.status_text})"


class VenueUtil:
    """体育场馆 API 工具类。"""

    BASE_URL = "http://202.117.17.144:8080"
    # 支付相关（浏览器手动登录后再支付，绕开 cookie 注入限制）
    PAY_BASE_URL = "http://202.117.17.144"
    LOGIN_URL = f"{PAY_BASE_URL}/xjtu/cas/login.html"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

    def __init__(self, session: requests.Session):
        self.session = session

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """统一请求方法，自动添加 /web/ 前缀、Referer 和 UA。"""
        url = f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Referer", f"{self.BASE_URL}/web/index.html")
        headers.setdefault("User-Agent", self.UA)
        _log.debug("_request: %s %s headers=%s data_keys=%s",
                   method, url, dict(headers), list(kwargs.get("data", {}).keys()))
        r = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
        # 非开放时间等场景：服务器返回 200 + HTML 提示页而非 JSON。
        if r.status_code == 200:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "json" not in ctype and ("html" in ctype or r.text.lstrip().startswith("<")):
                msg = self._extract_html_message(r)
                _log.info("_request: HTML response instead of JSON: %s", msg)
                raise VenueAPIError(msg or "服务暂时不可用")
        return r

    @staticmethod
    def _extract_html_message(r: requests.Response) -> str:
        """Try to pull the human-readable notice out of an HTML page."""
        text = r.text
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                decoded = r.content.decode(enc)
                if "<title>" in decoded or "<body" in decoded:
                    text = decoded
                    break
            except (UnicodeDecodeError, LookupError):
                continue
        m = re.search(r"<title>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
        if m:
            t = m.group(1).strip()
            if t:
                return t
        # fallback: first meaningful text node
        body = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        return body[:80] if body else ""

    # ------------------------------------------------------------------
    # 场馆列表
    # ------------------------------------------------------------------

    def get_venues(self) -> list[VenueInfo]:
        """获取场馆列表（从 JSON API 分页获取）。"""
        venues: list[VenueInfo] = []
        page = 1
        while True:
            r = self._request("GET", "/web/product/productData.html", params={
                "page": str(page),
                "rows": "8",
                "merccode": "100001",
                "remark": "defaultProList",
            })
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                venues.append(VenueInfo(
                    venue_id=item.get("id", 0),
                    name=self._decode(item.get("name", "")),
                    address=self._decode(item.get("address", "")),
                    icon=item.get("icon", ""),
                    category=item.get("firstchart", ""),
                    advanceday=int(item.get("advanceday", 7)),
                    advancenum=int(item.get("advancenum", 8)),
                ))
            page += 1
            if len(data) < 8:
                break

        return venues

    # ------------------------------------------------------------------
    # 时段查询
    # ------------------------------------------------------------------

    def get_available_slots(self, service_id: int, date_str: str) -> list[AreaSlot]:
        """获取可预订时段。"""
        r = self._request("GET", "/web/product/findOkArea.html", params={
            "s_date": date_str,
            "serviceid": str(service_id),
        })
        r.raise_for_status()
        return self._parse_slots(r.json(), date_str, str(service_id))

    def get_locked_slots(self, service_id: int, date_str: str) -> list[AreaSlot]:
        """获取已被锁定的时段。"""
        r = self._request("GET", "/web/product/findLockArea.html", params={
            "s_date": date_str,
            "serviceid": str(service_id),
        })
        r.raise_for_status()
        return self._parse_slots(r.json(), date_str, str(service_id))

    @staticmethod
    def _parse_slots(data: dict, date_str: str, service_id: str) -> list[AreaSlot]:
        """解析时段 JSON（findOkArea / findLockArea 通用）。"""
        items = data.get("object")
        if not isinstance(items, list):
            return []
        slots: list[AreaSlot] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            stock = item.get("stock", {}) or {}
            slots.append(AreaSlot(
                area_id=item.get("id", 0),
                area_name=item.get("sname", ""),
                stock_id=item.get("stockid", 0),
                time_slot=stock.get("time_no", ""),
                price=float(stock.get("price", 0)),
                date_str=date_str,
                status=int(item.get("status", 0)),
                using_num=int(stock.get("using_num", 0)),
                all_count=int(stock.get("all_count", 0)),
            ))
        return slots

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _decode(text: str) -> str:
        """处理可能的 GBK 乱码（服务器返回 GBK 编码时 requests 可能误判为 latin-1）。"""
        if text and any(ord(c) > 127 and ord(c) < 256 for c in text):
            try:
                return text.encode("latin-1").decode("gbk")
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
        return text

    # ------------------------------------------------------------------
    # 预订
    # ------------------------------------------------------------------

    def book(self, service_id: int, selections: list[tuple[int, int]],
             yzm: str) -> dict:
        """提交预订。

        selections: [(area_id, stock_id), ...] 可一次预订多个时段。
        注意 stockdetail 的 key 是 stock_id，value 是 area_id（与 HAR/Android 一致）；
        同一 stock_id 下多个 area_id 用逗号连接（前端 applySeat 逻辑）。
        """
        stockdetail: dict[str, str] = {}
        for area_id, stock_id in selections:
            key = str(stock_id)
            if key in stockdetail:
                stockdetail[key] += "," + str(area_id)
            else:
                stockdetail[key] = str(area_id)
        param = json.dumps({
            "stockdetail": stockdetail,
            "venueReason": "", "fileUrl": "", "address": str(service_id),
        })
        headers = {
            "Referer": f"{self.BASE_URL}/web/product/show.html?id={service_id}",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": self.BASE_URL,
        }
        # 服务端行为：首次 POST 可能返回 404；即使 200，首次提交同一
        # yzm 可能误报“验证码有误”，重试同一次请求即可通过。
        last_r = None
        for attempt in range(3):
            r = self._request("POST", "/web/order/tobook.html", data={
                "param": param, "yzm": yzm, "json": "true",
            }, headers=headers, _skip_auth_check=True)
            last_r = r
            if r.status_code != 200:
                _log.info("book: attempt %d status=%s, retrying",
                          attempt + 1, r.status_code)
                continue
            data = r.json()
            msg = str(data.get("message", ""))
            if data.get("result") == "100" and "验证码" in msg:
                _log.info("book: captcha rejected (attempt %d), "
                          "retry same yzm", attempt + 1)
                continue
            return data
        last_r.raise_for_status()
        return last_r.json()

    @staticmethod
    def pay_url(orderid: str) -> str:
        """订单支付页面 URL（拉起系统浏览器用，需先在浏览器登录）。"""
        return f"{VenueUtil.PAY_BASE_URL}/pay/show.html?id={orderid}"

    # ------------------------------------------------------------------
    # 订单
    # ------------------------------------------------------------------

    def get_orders(self) -> list[OrderInfo]:
        """获取全部订单（循环分页拉取，每页 20 条）。"""
        orders: list[OrderInfo] = []
        page = 1
        while True:
            r = self._request("GET", "/web/yyuser/searchorder.html", params={
                "page": str(page), "rows": "20",
                "status": "", "iscomment": "",
                "stockSDate": "", "stockEDate": "",
            })
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                break
            for item in data:
                if isinstance(item, dict):
                    orders.append(self._parse_order(item))
            if len(data) < 20:
                break
            page += 1
        # 按下单时间倒序（新的在前）
        orders.sort(key=lambda o: o.createdate, reverse=True)
        return orders

    @staticmethod
    def _parse_order(item: dict) -> OrderInfo:
        """解析单个订单 dict 为 OrderInfo。"""
        details: list[OrderDetail] = []
        od_list = item.get("orderdetail")
        if isinstance(od_list, list):
            for od in od_list:
                if not isinstance(od, dict):
                    continue
                stock = od.get("stock") or {}
                sd = od.get("stockdetail") or {}
                svc = od.get("service") or {}
                details.append(OrderDetail(
                    date_str=stock.get("s_date") or "",
                    time_slot=stock.get("time_no") or "",
                    area_name=sd.get("sname") or "",
                    price=od.get("price") or 0,
                    service_id=str(od.get("serviceid") or ""),
                    service_name=svc.get("name") or "",
                ))
        return OrderInfo(
            orderid=item.get("orderid") or "",
            status=int(item.get("status") or 0),
            createdate=item.get("createdate") or "",
            price=item.get("price") or 0,
            details=details,
        )

    def cancel_order(self, orderid: str) -> dict:
        """取消订单。返回 {result, message}。"""
        r = self._request("POST", "/web/order/delorder.html", data={
            "orderid": str(orderid), "json": "true",
        }, headers={
            "Referer": f"{self.BASE_URL}/web/yyuser/searchorder.html",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": self.BASE_URL,
        })
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return {"result": "0", "message": r.text[:100]}
