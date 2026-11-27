"""问舟的智慧社区活动工具：查、看、报、取消、我的报名。"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from ss import Activity, Order, SsActivity, SsError

from .providers import ToolCall, ToolDefinition

ACTIVITY_TOOL = ToolDefinition(
    "activity",
    "学校智慧社区的活动报名，是集体活动证明和课外学分（第二课堂，本科共需 8 学分）的主要来源。"
    "活动描述几乎不写「集体活动证明」，但讲座、报告会、分享会、宣讲会（如高数讲座、保研分享会）通常都能开；"
    "用户要集体活动证明时用 group_proof，它按这类关键词合并搜出未结束的活动。"
    "结果里的课程性质、素养能力、积分是课外学分的参考，能否认定以学院、书院规定为准。"
    "search 按名称搜（keyword 缺省列近期活动）；detail 看详情（报名起止、名额、是否已报、地点、积分构成）；mine 本人报名记录。"
    "apply 一键报名、cancel 取消报名：先 detail 核对仍在报名时间内且未报过，并经用户明确同意。",
    {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["group_proof", "search", "detail", "apply", "cancel", "mine"],
                "description": "group_proof / search / detail / apply / cancel / mine。",
            },
            "keyword": {"type": "string", "description": "search 的活动名称关键词。"},
            "id": {"type": "string", "description": "活动 ID（HDDM），来自 search 或 mine。detail / apply / cancel 必填。"},
            "order": {
                "type": "string",
                "enum": ["time", "hot", "points"],
                "description": "search 排序：time 时间（默认）、hot 热度、points 积分。",
            },
        },
        "required": ["action"],
    },
)

_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_ORDERS = {"hot": Order.HOT, "points": Order.POINTS}


def _plain(html_text: str) -> str:
    return " ".join(_TAGS.sub(" ", html_text).replace("&nbsp;", " ").split())


def _line(a: Activity) -> str:
    parts = [
        f"id {a.id}", a.title, a.status.value, a.start, a.type, a.org, a.nature, a.ability,
        f"积分 {a.points}" if a.points not in ("", "0") else "",
        f"{a.participants} 人参与",
        "讲座类，常可开集体活动证明" if a.likely_group_proof else "",
    ]
    return "｜".join(p for p in parts if p)


def run_activity(api: SsActivity, arguments: Mapping[str, object]) -> str:
    """执行一次 activity 调用，返回给模型的文本。apply 前代码侧再核一遍报名时间，不全指望模型。"""
    action = str(arguments.get("action") or "search")
    activity_id = str(arguments.get("id") or "").strip()
    if action == "group_proof":
        rows = api.group_proof_candidates()[:20]
        if not rows:
            return "没有未结束的讲座、报告、分享类活动"
        return "未结束的讲座、报告、分享类活动（逐个 detail 看能否报名）：\n" + "\n".join(map(_line, rows))
    if action == "search":
        order = _ORDERS.get(str(arguments.get("order") or ""), Order.TIME)
        rows = api.list(str(arguments.get("keyword") or ""), order)
        return "\n".join(map(_line, rows)) or "没有找到活动"
    if action == "mine":
        rows = api.my_applies()
        return "\n".join(
            "｜".join(p for p in (f"id {a.activity_id}", a.title, a.start, a.activity_status,
                                   f"审核 {a.review}" if a.review else "") if p)
            for a in rows
        ) or "还没有报名记录"
    if action not in ("detail", "apply", "cancel"):
        return "错误：action 只能是 group_proof, search, detail, apply, cancel, mine"
    if not activity_id:
        return "错误：缺少 id"
    d = api.detail(activity_id)
    if action == "apply":
        blocker = d.apply_blocker()
        if blocker:
            return f"未报名：{blocker}"
        api.apply(activity_id)
        return f"已报名：{d.base.title}" + ("；需审核，结果看 mine" if d.need_review else "")
    if action == "cancel":
        if not d.applied:
            return "未取消：还没报名"
        if not d.can_cancel:
            return "未取消：这个活动不允许取消报名"
        api.cancel(activity_id)
        return f"已取消报名：{d.base.title}"
    lines = [_line(d.base)]
    if d.place:
        lines.append(f"地点：{d.place}")
    if d.scope:
        lines.append(f"范围：{d.scope}")
    if d.explicit_tags:
        lines.append("描述中写明：" + "、".join(d.explicit_tags))
    if d.need_apply:
        quota = f"，名额 {d.quota}" if d.quota else ""
        state = "已报名" if d.applied else (d.apply_blocker() or "现在可一键报名")
        lines.append(f"报名：{d.apply_start} 至 {d.apply_end}{quota}，{state}")
    else:
        lines.append("无需报名")
    if d.points_breakdown:
        lines.append(f"积分构成：{d.points_breakdown}")
    if d.onsite_sign_in:
        lines.append("需现场签到（在「活动报名」页面输验证码）")
    body = _plain(d.content_html)[:1500]
    if body:
        lines.append(f"正文：{body}")
    if d.notice:
        lines.append(f"须知：{d.notice[:500]}")
    return "\n".join(lines)


def make_activity_runner(session_factory: Callable[[], object]) -> Callable[[ToolCall], str]:
    """session_factory 在工作线程里登录智慧社区并返回会话；同一次请求只登录一次。"""
    api: SsActivity | None = None

    def run(call: ToolCall) -> str:
        nonlocal api
        if call.name != ACTIVITY_TOOL.name:
            return f"错误：未知工具 {call.name}"
        try:
            if api is None:
                api = SsActivity(session_factory())
            return run_activity(api, call.arguments)
        except SsError as error:
            return f"失败：{error}"
        except Exception as error:
            return f"失败：{error or type(error).__name__}"

    return run
