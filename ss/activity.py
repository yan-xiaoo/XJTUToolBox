"""西交学生智慧社区（ss.xjtu.edu.cn，金智 EMAP）活动报名接口。

一律 ``POST <ctrl>/<fn>.do``，表单 ``data=<JSON>``，返回 ``{code: "0", msg, data}``。
不调 saveAccessRecord / saveBrowseScore：看一眼详情就记浏览分不合适。
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass
from datetime import datetime

HOST = "ss.xjtu.edu.cn"
APP_NAME = "swmsyxsfzapp"
APP_BASE = f"https://{HOST}/xsfw/sys/{APP_NAME}"
APP_INDEX = f"{APP_BASE}/*default/index.do"
PUB_BASE = f"https://{HOST}/xsfw/sys/swpubapp"
# 首页 WIS_CONFIG.APPID；页面里取不到时用这个（2026-11 实测值）
DEFAULT_APP_ID = "6474976736708742"


def web_url(activity_id: str) -> str:
    """官方网页的活动详情（附件 / 团体报名只能在网页里做）。"""
    return f"{APP_INDEX}#/hdxq?HDDM={activity_id}"


# 讲座、报告、分享会一类常能开集体活动证明，活动描述里多半不写
GROUP_PROOF_WORDS = ("讲座", "报告", "分享", "宣讲", "论坛", "沙龙", "交流会", "座谈")
# 描述里出现即可确认的标签词
EXPLICIT_TAG_WORDS = ("集体活动", "校级活动", "院级活动")
_TAGS_AND_SPACE = re.compile(r"<[^>]*>|&nbsp;|&#160;|\s|　")
_TIME = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?")


class SsError(RuntimeError):
    """智慧社区返回失败（code≠0、HTTP 错误或格式异常）。"""


class ActivityStatus(enum.Enum):
    UPCOMING = "未开始"
    ONGOING = "进行中"
    ENDED = "已结束"


class ApplyMode(enum.Enum):
    ONE_CLICK = "一键报名"
    ATTACHMENT = "附件报名"
    GROUP = "团体报名"


class Order(enum.Enum):
    TIME = "-XC_HDSFKS,+HDKSSJ,-CYRS"
    HOT = "-CYRS"
    POINTS = "-HDZF"


def parse_time(text: str) -> datetime | None:
    """「2026-11-20 08:00(:00)」→ datetime；认不出给 None。"""
    m = _TIME.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0))
    except ValueError:
        return None


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def _flag(value) -> bool:
    return _s(value).lower() in {"1", "true", "是", "y", "yes"}


def _status(code: str) -> ActivityStatus:
    code = code.upper()
    if code == "JXZ":
        return ActivityStatus.ONGOING
    if code == "YJS":
        return ActivityStatus.ENDED
    return ActivityStatus.UPCOMING


def _absolute(url: str) -> str:
    return url if url.startswith("http") else f"https://{HOST}/{url.lstrip('/')}"


@dataclass(frozen=True)
class Activity:
    id: str
    title: str
    type: str
    org: str
    start: str
    end: str
    status: ActivityStatus
    participants: int
    points: str
    cover: str | None = None
    # 课程性质与素养能力类别：课外学分认定看这两项
    nature: str = ""
    ability: str = ""
    # 列表没给 SFXYBM 时为 None（不显示「无需报名」）
    need_apply: bool | None = None

    @property
    def likely_group_proof(self) -> bool:
        return any(word in self.title for word in GROUP_PROOF_WORDS)

    @classmethod
    def from_row(cls, o: dict) -> Activity:
        try:
            participants = int(float(_s(o.get("CYRS")) or 0))
        except ValueError:
            participants = 0
        cover = _s(o.get("ZPURL")) or _s(o.get("HDFM_URL"))
        return cls(
            id=_s(o.get("HDDM")),
            title=_s(o.get("HDMC")),
            type=_s(o.get("HDLX_DISPLAY")),
            org=_s(o.get("SSBM_DISPLAY")),
            start=_s(o.get("HDKSSJ")) or _s(o.get("HDRQ")),
            end=_s(o.get("HDJSSJ")),
            status=_status(_s(o.get("HDZT"))),
            participants=participants,
            points=_s(o.get("HDZF")),
            cover=_absolute(cover) if cover else None,
            nature=_s(o.get("KCXZ_DISPLAY")),
            ability=_s(o.get("SYNLDM_DISPLAY")),
            need_apply=_flag(o.get("SFXYBM")) if _s(o.get("SFXYBM")) else None,
        )


def activity_tags(a: Activity, explicit: list[str] | None = None, need_apply: bool | None = None) -> list[tuple[str, bool]]:
    """列表行的标签 (文字, 是否确认)：详情里明写的标签算确认；没写「集体活动」但标题像讲座的标「疑似」。"""
    explicit = explicit or []
    tags = [(word, True) for word in explicit]
    if a.likely_group_proof and "集体活动" not in explicit:
        tags.append(("疑似集体活动", False))
    if (a.need_apply if need_apply is None else need_apply) is False:
        tags.append(("无需报名", False))
    tags += [(text, False) for text in (a.nature, a.ability) if text]
    return tags


@dataclass(frozen=True)
class ActivityDetail:
    base: Activity
    content_html: str
    notice: str
    place: str
    need_apply: bool
    apply_mode: ApplyMode
    apply_start: str
    apply_end: str
    quota: int | None
    need_review: bool
    applied: bool
    # 与官方详情页同一判据：已报名、仍在报名期内、且不在签到期（或在签到期但还没签到）
    can_cancel: bool
    onsite_sign_in: bool
    scope: str = ""
    points_breakdown: str = ""
    # 正文 + 须知去掉 HTML 与空白：「集<span>体</span> 活动」也要认得
    search_text: str = ""

    @property
    def explicit_tags(self) -> list[str]:
        """描述里明写的「集体活动 / 校级活动 / 院级活动」；发布范围不等于活动能算哪一级。"""
        return [word for word in EXPLICIT_TAG_WORDS if word in self.search_text]

    def apply_blocker(self, now: datetime | None = None) -> str | None:
        """现在能不能一键报名；不能时给出原因。"""
        now = now or datetime.now()
        start, end = parse_time(self.apply_start), parse_time(self.apply_end)
        if not self.need_apply:
            return "这个活动不用报名"
        if self.applied:
            return "已经报过名了"
        if self.base.status is ActivityStatus.ENDED:
            return "活动已结束"
        if start and now < start:
            return f"报名还没开始（{self.apply_start} 开始）"
        if end and now > end:
            return f"报名已截止（{self.apply_end} 截止）"
        if self.apply_mode is not ApplyMode.ONE_CLICK:
            return f"这个活动要{self.apply_mode.value}，请到网页里报"
        return None

    @classmethod
    def from_row(cls, o: dict) -> ActivityDetail:
        content, notice = _s(o.get("HDNR")), _s(o.get("HDXZ"))
        quota = _s(o.get("BMXZRS"))
        breakdown = [
            f"{label} {_s(o.get(key))}"
            for label, key in (("浏览", "LLF"), ("报名", "BMF"), ("签到", "QDF"), ("机动", "JDF"))
            if _s(o.get(key)) not in ("", "0")
        ]
        return cls(
            base=Activity.from_row(o),
            content_html=content,
            notice=notice,
            place=" ".join(p for p in (_s(o.get("JBDD_DISPLAY")), _s(o.get("XXDD"))) if p),
            need_apply=_flag(o.get("SFXYBM")),
            apply_mode={"2": ApplyMode.ATTACHMENT, "3": ApplyMode.GROUP}.get(_s(o.get("BMFS")), ApplyMode.ONE_CLICK),
            apply_start=_s(o.get("BMKSSJ")),
            apply_end=_s(o.get("BMJSSJ")),
            quota=int(quota) if quota.isdigit() and int(quota) > 0 else None,
            need_review=_flag(o.get("BMSH")),
            applied=_flag(o.get("HASAPPLY")),
            can_cancel=_flag(o.get("HASAPPLY")) and _flag(o.get("SFXYBM")) and _flag(o.get("SFZBMSJN"))
            and (not _flag(o.get("SFZQDSJN")) or (_flag(o.get("SFXCQD")) and _s(o.get("YZMZT")) == "1")),
            onsite_sign_in=_flag(o.get("SFXCQD")),
            scope=_s(o.get("FBFW_DISPLAY")),
            points_breakdown=" · ".join(breakdown),
            search_text=_TAGS_AND_SPACE.sub("", f"{content}|{notice}"),
        )


@dataclass(frozen=True)
class MyApply:
    activity_id: str
    title: str
    review: str
    activity_status: str
    start: str

    @classmethod
    def from_row(cls, o: dict) -> MyApply:
        review = _s(o.get("SHZT_DISPLAY")) or {"": "", "99": "已通过"}.get(_s(o.get("SHZT")), "审核中")
        # 这个接口的 HDZT 是数字：1 未开始 / 2 进行中 / 其余已结束
        code = _s(o.get("HDZT"))
        if code == "1":
            status = ActivityStatus.UPCOMING
        elif code == "2":
            status = ActivityStatus.ONGOING
        elif code.isdigit():
            status = ActivityStatus.ENDED
        else:
            status = _status(code)
        return cls(
            activity_id=_s(o.get("HDDM")),
            title=_s(o.get("HDMC")),
            review=review,
            activity_status=status.value,
            start=_s(o.get("HDKSSJ")) or _s(o.get("HDRQ")),
        )


def _rows(data) -> list[dict]:
    """列表接口的 data 有时直接是数组，有时包一层 {rows: [...]}，按第一个数组取。"""
    if isinstance(data, list):
        return [one for one in data if isinstance(one, dict)]
    if isinstance(data, dict):
        rows = data.get("rows")
        if not isinstance(rows, list):
            rows = next((v for v in data.values() if isinstance(v, list)), [])
        return [one for one in rows if isinstance(one, dict)]
    return []


def _single(data) -> dict | None:
    if isinstance(data, dict):
        if "HDDM" in data or "HDMC" in data:
            return data
        rows = _rows(data)
        if rows:
            return rows[0]
        return next((v for v in data.values() if isinstance(v, dict)), None)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class SsActivity:
    """智慧社区活动：列表、详情、一键报名、取消、现场签到、我的报名。"""

    def __init__(self, session):
        self.session = session

    def _call(self, path: str, data: dict):
        response = self.session.post(
            f"{APP_BASE}/{path}",
            data={"data": _dump(data)},
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": APP_INDEX,
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise SsError(f"智慧社区返回 HTTP {response.status_code}")
        try:
            root = response.json()
        except ValueError:
            raise SsError("智慧社区返回格式异常") from None
        if not isinstance(root, dict):
            raise SsError("智慧社区返回格式异常")
        if _s(root.get("code")) != "0":
            raise SsError(_s(root.get("msg")) or "智慧社区请求失败")
        return root.get("data")

    def list(self, keyword: str = "", order: Order = Order.TIME, page: int = 1, page_size: int = 20) -> list[Activity]:
        """活动列表。keyword 按名称搜；取不满一页就是到底了。"""
        keyword = keyword.strip()
        query = [[{"name": "HDMC", "value": keyword, "builder": "include", "linkOpt": "AND"}]] if keyword else []
        data = self._call("ykHdController/getActivityList.do", {
            "querySetting": _dump(query) if query else "[]",
            "orderColumns": order.value,
            "pageNumber": page,
            "pageSize": page_size,
        })
        return [Activity.from_row(one) for one in _rows(data)]

    def group_proof_candidates(self, per_word: int = 10) -> list[Activity]:
        """能开集体活动证明的候选：列表接口一次只认一个名称条件，按关键词逐个搜再合并。"""
        seen: dict[str, Activity] = {}
        for word in GROUP_PROOF_WORDS:
            for one in self.list(word, Order.TIME, 1, per_word):
                if one.status is not ActivityStatus.ENDED:
                    seen.setdefault(one.id, one)
        return sorted(seen.values(), key=lambda a: parse_time(a.start) or datetime.max)

    def detail(self, activity_id: str) -> ActivityDetail:
        row = _single(self._call("ykHdController/getActivityDetail.do", {"HDDM": activity_id}))
        if row is None:
            raise SsError("没找到这个活动")
        return ActivityDetail.from_row(row)

    def apply(self, activity_id: str) -> None:
        """一键报名。截止校验在服务端保存时才做，调用方先看 ActivityDetail.apply_blocker。"""
        body = {"HDDM": activity_id}
        self._call("hdController/checkCurUserApply.do", body)
        self._call("hdController/saveActivityApply.do", body)

    def cancel(self, activity_id: str) -> None:
        self._call("ykHdController/cancelBm.do", {"HDDM": activity_id})

    def sign_in(self, activity_id: str, code: str) -> None:
        """现场签到 / 签退：输入现场给的 6 位验证码（不做定位）。"""
        self._call("ykHdController/saveCcQdqt.do", {"HDDM": activity_id, "YZM": code.strip()})

    def my_applies(self, page: int = 1, page_size: int = 30) -> list[MyApply]:
        data = self._call("myInfoController/getWdbmInfo.do", {"PAGENUM": page, "PAGESIZE": page_size, "querySetting": "[]"})
        return [MyApply.from_row(one) for one in _rows(data)]
