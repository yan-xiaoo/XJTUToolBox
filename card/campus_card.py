from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Protocol

import requests

from auth import ServerError


class CampusCardTransport(Protocol):
    """校园卡接口所需的最小 HTTP 传输接口。"""

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        ...


@dataclass(frozen=True)
class CardProfile:
    """登录后由上层提供的校园卡用户资料。"""

    name: str
    student_no: str
    account: str

    def __post_init__(self) -> None:
        for field in ("name", "student_no", "account"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"校园卡用户资料缺少{field}字段")


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

    def __init__(self, transport: CampusCardTransport, profile: CardProfile):
        if not isinstance(profile, CardProfile):
            raise TypeError("profile must be a CardProfile")
        self.transport = transport
        self.profile = profile

    def get_card_info(self) -> CardInfo:
        operation = "查询校园卡"
        response = self.transport.get(
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
            name=self.profile.name,
            student_no=self.profile.student_no,
            account=self.profile.account,
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
        response = self.transport.get(
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
                amount_cents=_signed_amount_cents(
                    amount_cents, type_name, icon,
                    type_from=_optional_str(item.get("typeFrom")),
                    to_account=_optional_int(item.get("toAccount")),
                    from_account=_optional_int(item.get("fromAccount")),
                ),
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
                page_payload = json.dumps(
                    [asdict(item) for item in batch],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                page_signature = hashlib.sha256(page_payload).hexdigest()
                if page_signature in seen_pages:
                    raise ServerError(1, f"{operation}返回了重复分页数据")
                seen_pages.add(page_signature)
                records.extend(batch)

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


_INCOME_MARKERS = ("充值", "圈存", "退款", "补助", "recharge", "transfer-in", "refund", "subsidy")
_EXPENSE_MARKERS = (
    "消费", "支出", "扣款", "consume", "expense", "transfer-out",
    # 食堂窗口扫码支付走独立通道：icon=qrCode-payment / turnoverType=二维码支付，
    # 不在上面的词里，会落到默认分支被当成正数收入。
    "二维码支付", "qrcode-payment",
)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _signed_amount_cents(
    raw_amount: int,
    type_name: str,
    icon: str,
    type_from: str | None = None,
    to_account: int | None = None,
    from_account: int | None = None,
) -> int:
    """确定流水金额方向。

    优先用 ``typeFrom``：官方 ncard 账单页前端按 ``"1" === typeFrom`` 显示 +，
    其余一律显示 -，这是权威规则。缺失时才退回类型文案关键词；关键词也对不上时，
    看钱最终落到哪个账号——充值 ``toAccount=0``（钱没转出去），消费/扫码支付
    ``toAccount=商户终端账号``（转出去了）。
    """
    if raw_amount < 0:
        return raw_amount
    if type_from:
        return abs(raw_amount) if type_from == "1" else -abs(raw_amount)
    normalized = f"{type_name} {icon}".casefold()
    # 收入必须先判断：例如“消费退款”同时包含支出和收入标记，退款应取正。
    if any(marker.casefold() in normalized for marker in _INCOME_MARKERS):
        return abs(raw_amount)
    if any(marker.casefold() in normalized for marker in _EXPENSE_MARKERS):
        return -abs(raw_amount)
    # 学校新增了没见过的支付渠道文案：与其盲目当收入，不如看钱实际去哪了。
    if to_account is not None:
        stays_on_card = to_account == 0 or (from_account is not None and to_account == from_account)
        return abs(raw_amount) if stays_on_card else -abs(raw_amount)
    return raw_amount


def _json_object(response: requests.Response, operation: str) -> dict[str, Any]:
    if not response.ok:
        raise ServerError(1, f"{operation}请求失败")
    text = response.text or ""
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
        code = payload.get("code", 1)
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
        digits = text.removeprefix("-")
        if text and digits.isascii() and digits.isdigit():
            return int(text)
    raise ServerError(1, f"{operation}返回的{field}格式错误")
