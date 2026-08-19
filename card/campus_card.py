from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from auth import ServerError


@dataclass
class CardInfo:
    name: str
    student_no: str
    account: str
    balance: float
    pending_amount: float
    lost: bool
    frozen: bool
    expire_date: str
    card_type: str


@dataclass
class CardTransaction:
    time: str
    amount: float
    merchant: str
    balance: float
    type_name: str
    description: str


class CampusCard:
    BASE = "https://ncard.xjtu.edu.cn"

    def __init__(self, session: requests.Session):
        self.session = session

    def get_card_info(self) -> CardInfo:
        response = self.session.get(
            f"{self.BASE}/berserker-app/ykt/tsm/queryCard?synAccessSource=h5",
            timeout=20,
        )
        payload = _json(response)
        if payload.get("code") != 200:
            raise ServerError(payload.get("code") or 1, payload.get("message") or "查询校园卡失败")
        cards = ((payload.get("data") or {}).get("card") or [])
        card = cards[0] if cards else {}
        expire = str(card.get("expdate") or "")
        if len(expire) == 8:
            expire = f"{expire[:4]}-{expire[4:6]}-{expire[6:]}"
        headers = getattr(self.session, "headers", {})
        return CardInfo(
            name=str(headers.get("X-Card-Name") or ""),
            student_no=str(headers.get("X-Card-Sno") or ""),
            account=str(headers.get("X-Card-Account") or ""),
            balance=_fen(card.get("elec_accamt")),
            pending_amount=_fen(card.get("unsettle_amount")),
            lost=card.get("barflag") == 1,
            frozen=card.get("freezeflag") == 1,
            expire_date=expire,
            card_type=str(card.get("cardname") or ""),
        )

    def get_transactions(
            self,
            time_from: date | None = None,
            time_to: date | None = None,
            page: int = 1,
            page_size: int = 30) -> tuple[int, list[CardTransaction]]:
        end = time_to or date.today()
        start = time_from or (end - timedelta(days=90))
        response = self.session.get(
            f"{self.BASE}/berserker-search/search/personal/turnover",
            params={
                "size": page_size,
                "current": page,
                "timeFrom": start.isoformat(),
                "timeTo": end.isoformat(),
                "synAccessSource": "h5",
            },
            timeout=20,
        )
        payload = _json(response)
        if payload.get("code") != 200:
            raise ServerError(
                payload.get("code") or 1,
                payload.get("message") or "查询校园卡流水失败",
            )
        data = payload.get("data") or {}
        records = []
        for item in data.get("records") or []:
            amount = _fen(item.get("tranamt"))
            type_name = str(item.get("turnoverType") or "")
            if item.get("icon") != "recharge" and "充值" not in type_name and "圈存" not in type_name:
                amount = -abs(amount)
            resume = str(item.get("resume") or "")
            merchant = str(item.get("toMerchant") or resume.split("-", 1)[0])
            records.append(CardTransaction(
                time=str(item.get("jndatetimeStr") or ""),
                amount=amount,
                merchant=merchant,
                balance=_fen(item.get("cardBalance")),
                type_name=type_name,
                description=resume,
            ))
        return int(data.get("total") or len(records)), records

    def get_all_transactions(
            self,
            time_from: date | None = None,
            time_to: date | None = None,
            page_size: int = 80) -> tuple[int, list[CardTransaction]]:
        records: list[CardTransaction] = []
        page = 1
        total = 0
        while True:
            total, batch = self.get_transactions(time_from, time_to, page=page, page_size=page_size)
            records.extend(batch)
            if not batch or len(records) >= total:
                break
            page += 1
        return total, records


def _fen(value: Any) -> float:
    try:
        return float(value or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _json(response: requests.Response) -> dict:
    if "移动端模式" in (response.text or ""):
        raise ServerError(1, "请浏览器调成移动端模式访问！")
    try:
        return response.json()
    except ValueError as exc:
        raise ServerError(1, "校园卡接口返回了无法解析的数据") from exc
