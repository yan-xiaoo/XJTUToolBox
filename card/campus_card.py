from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

import requests

from auth import ServerError


@dataclass
class CardInfo:
    name: str
    student_no: str
    account: str
    balance_cents: int
    pending_amount_cents: int
    lost: bool
    frozen: bool
    expire_date: str
    card_type: str

    @property
    def balance(self) -> float:
        """返回仅用于界面展示的元金额。"""
        return self.balance_cents / 100

    @property
    def pending_amount(self) -> float:
        """返回仅用于界面展示的元金额。"""
        return self.pending_amount_cents / 100


@dataclass
class CardTransaction:
    time: str
    amount_cents: int
    merchant: str
    balance_cents: int
    type_name: str
    description: str

    @property
    def amount(self) -> float:
        """返回仅用于界面展示的元金额。"""
        return self.amount_cents / 100

    @property
    def balance(self) -> float:
        """返回仅用于界面展示的元金额。"""
        return self.balance_cents / 100


class CampusCard:
    BASE = "https://ncard.xjtu.edu.cn"

    def __init__(self, session: requests.Session):
        self.session = session

    def get_card_info(self) -> CardInfo:
        operation = "查询校园卡"
        response = self.session.get(
            f"{self.BASE}/berserker-app/ykt/tsm/queryCard?synAccessSource=h5",
            timeout=20,
        )
        payload = _json_object(response, operation)
        _require_success(payload, operation)
        data = _data_object(payload, operation)
        cards = _required_list(data, "card", operation)
        if not cards:
            raise ServerError(1, f"{operation}返回了空卡片数据")
        card = cards[0]
        if not isinstance(card, dict):
            raise ServerError(1, f"{operation}返回的卡片数据格式错误")

        expire = str(card.get("expdate") or "")
        if len(expire) == 8:
            expire = f"{expire[:4]}-{expire[4:6]}-{expire[6:]}"
        return CardInfo(
            name=str(getattr(self.session, "user_name", "") or ""),
            student_no=str(getattr(self.session, "student_no", "") or ""),
            account=str(getattr(self.session, "card_account", "") or ""),
            balance_cents=_integer(card.get("elec_accamt"), "余额", operation),
            pending_amount_cents=_integer(card.get("unsettle_amount"), "未结算金额", operation),
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
        operation = "查询校园卡流水"
        if page <= 0 or page_size <= 0:
            raise ServerError(1, f"{operation}的分页参数必须为正数")
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
        payload = _json_object(response, operation)
        _require_success(payload, operation)
        data = _data_object(payload, operation)
        total = _integer(data.get("total"), "流水总数", operation)
        if total < 0:
            raise ServerError(1, f"{operation}返回的流水总数格式错误")
        raw_records = _required_list(data, "records", operation)

        records: list[CardTransaction] = []
        for item in raw_records:
            if not isinstance(item, dict):
                raise ServerError(1, f"{operation}返回的流水记录格式错误")
            amount_cents = _integer(item.get("tranamt"), "流水金额", operation)
            type_name = str(item.get("turnoverType") or "")
            icon = str(item.get("icon") or "")
            resume = str(item.get("resume") or "")
            merchant = str(item.get("toMerchant") or resume.split("-", 1)[0])
            records.append(CardTransaction(
                time=str(item.get("jndatetimeStr") or ""),
                amount_cents=_signed_amount_cents(amount_cents, type_name, icon),
                merchant=merchant,
                balance_cents=_integer(item.get("cardBalance"), "流水余额", operation),
                type_name=type_name,
                description=resume,
            ))
        return total, records

    def get_all_transactions(
            self,
            time_from: date | None = None,
            time_to: date | None = None,
            page_size: int = 80) -> tuple[int, list[CardTransaction]]:
        operation = "查询校园卡流水"
        if page_size <= 0:
            raise ServerError(1, f"{operation}的分页参数必须为正数")

        records: list[CardTransaction] = []
        seen_pages: set[str] = set()
        expected_total: int | None = None
        max_pages = 1

        page = 1
        while page <= max_pages:
            total, batch = self.get_transactions(
                time_from, time_to, page=page, page_size=page_size,
            )
            if expected_total is None:
                expected_total = total
                max_pages = max(1, (total + page_size - 1) // page_size)
            elif total != expected_total:
                raise ServerError(1, f"{operation}返回的总数在分页过程中发生变化")

            if batch:
                page_signature = json.dumps(
                    [asdict(item) for item in batch],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if page_signature in seen_pages:
                    raise ServerError(1, f"{operation}返回了重复分页数据")
                seen_pages.add(page_signature)
                records.extend(batch)

            if expected_total is None:
                raise ServerError(1, f"{operation}未返回总数")
            if len(records) > expected_total:
                raise ServerError(1, f"{operation}返回的流水记录超过总数")
            if not batch:
                if len(records) == expected_total:
                    return expected_total, records
                raise ServerError(1, f"{operation}返回了残缺流水数据")
            if len(records) == expected_total:
                return expected_total, records
            if page == max_pages:
                raise ServerError(1, f"{operation}返回了残缺流水数据")
            page += 1

        raise ServerError(1, f"{operation}返回了残缺流水数据")


_INCOME_MARKERS = ("充值", "圈存", "退款", "补助", "recharge", "transfer", "refund", "subsidy")
_EXPENSE_MARKERS = ("消费", "支出", "扣款", "consume", "expense")


def _signed_amount_cents(raw_amount: int, type_name: str, icon: str) -> int:
    """按服务端符号和已知流水类型确定金额方向。"""
    if raw_amount < 0:
        return raw_amount
    normalized = f"{type_name} {icon}".casefold()
    if any(marker.casefold() in normalized for marker in _INCOME_MARKERS):
        return abs(raw_amount)
    if any(marker.casefold() in normalized for marker in _EXPENSE_MARKERS):
        return -abs(raw_amount)
    return raw_amount


def _json_object(response: requests.Response, operation: str) -> dict[str, Any]:
    if not getattr(response, "ok", True):
        raise ServerError(1, f"{operation}请求失败")
    text = getattr(response, "text", "") or ""
    if "移动端模式" in text:
        raise ServerError(1, f"{operation}要求使用移动端模式")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ServerError(1, f"{operation}返回了无法解析的数据") from exc
    if not isinstance(payload, dict):
        raise ServerError(1, f"{operation}返回的数据格式错误")
    return payload


def _require_success(payload: dict[str, Any], operation: str) -> None:
    if "code" not in payload or str(payload.get("code")) != "200":
        code = payload.get("code") or 1
        message = payload.get("message") or "业务请求失败"
        raise ServerError(code, f"{operation}失败：{message}")


def _data_object(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ServerError(1, f"{operation}返回的数据格式错误")
    return data


def _required_list(data: dict[str, Any], key: str, operation: str) -> list[Any]:
    values = data.get(key)
    if not isinstance(values, list):
        raise ServerError(1, f"{operation}返回的{key}格式错误")
    return values


def _integer(value: Any, field: str, operation: str) -> int:
    if isinstance(value, bool):
        raise ServerError(1, f"{operation}返回的{field}格式错误")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and text.removeprefix("-").isdigit():
            return int(text)
    raise ServerError(1, f"{operation}返回的{field}格式错误")
