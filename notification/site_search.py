"""站内搜索：用各站自己的全文检索，而不是只在已经抓到的通知里筛。

本地筛只能在「已经抓到的那一两页」里找，半年前的通知永远搜不到；站内搜索查的是全站索引。

- 学院 / 部门站几乎都是博达 CMS，首页有个 ``search.jsp``（有的站叫 ``ssjgy.jsp``、``sou.jsp``）
  的全文检索表单。关键词 Base64 后放进 ``newskeycode2``，GET 就能翻页；每页约 15 条，每条带日期。
  结果按相关度排，旧通知常排在前面，所以取前两页再按日期倒序。
- 首页找不到检索表单、或检索结果不带完整日期的站，退回「抓列表前两页、本地按标题筛」。
"""

from __future__ import annotations

import base64
import datetime
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import quote, urljoin, urlparse

from lxml import etree

from .crawlers import create_crawler
from .crawlers.crawler import get_session, pass_challenge_for_website
from .notification import Notification
from .source import SourceDescriptor, source_registry

_FORM_ACTION_RE = re.compile(r'<form[^>]+action="/?([a-zA-Z0-9_]+\.jsp\?wbtreeid=\d+)"', re.IGNORECASE)
_DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
_CATEGORY_RE = re.compile(r"^\s*[\[【]([^\]】]{1,12})[\]】]\s*")
_ROW_TAGS = {"li", "tr", "dd", "div"}
_TIMEOUT = 20

# 搜索入口，按站点 origin 缓存；空串表示这个站没有博达检索，别每次都去首页找。
_actions: dict[str, str] = {}
_actions_lock = threading.Lock()


@dataclass
class SiteSearchResult:
    notifications: list[Notification]
    errors: dict[str, str] = field(default_factory=dict)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _session_for(source: SourceDescriptor):
    if not source.needs_challenge:
        return get_session()
    origin = _origin(source.url)
    return pass_challenge_for_website(source.url, f"{origin}/dynamic_challenge")


def _action_for(session, source: SourceDescriptor) -> str | None:
    """站点首页上博达检索表单的 action（相对站点根），没有返回 None。"""
    origin = _origin(source.url)
    with _actions_lock:
        if origin in _actions:
            return _actions[origin] or None
    try:
        response = session.get(f"{origin}/", timeout=_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return None  # 首页都打不开：不缓存结论，下次再试
    html = response.content.decode(response.encoding or "utf-8", errors="replace")
    action = ""
    # 只认带博达检索字段的表单，别把登录框之类的 jsp 当成搜索
    for match in _FORM_ACTION_RE.finditer(html):
        index = html.find("lucenenewssearchkey", match.start())
        if 0 <= index <= match.start() + 1500:
            action = match.group(1)
            break
    with _actions_lock:
        _actions[origin] = action
    return action or None


def _row_text(anchor) -> str:
    """日期和标题同在一行（li / tr / div），在它的文字里找。"""
    node = anchor.getparent()
    while node is not None and not (isinstance(node.tag, str) and node.tag.lower() in _ROW_TAGS):
        node = node.getparent()
    if node is None:
        node = anchor.getparent()
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _search_vsb(session, source: SourceDescriptor, action: str, keyword: str, page: int):
    """返回 (通知列表, 是否还有下一页, 搜到但没有完整日期的条数)。"""
    origin = _origin(source.url)
    key = base64.b64encode(keyword.encode("utf-8")).decode("ascii")
    url = f"{origin}/{action}&searchScope=0&currentnum={page}&newskeycode2={quote(key, safe='')}"
    response = session.get(url, timeout=_TIMEOUT)
    response.raise_for_status()
    root = etree.HTML(response.content, parser=etree.HTMLParser(recover=True))
    if root is None:
        return [], False, 0
    latest = datetime.date.today() + datetime.timedelta(days=7)
    undated = 0
    seen: set[str] = set()
    items: list[Notification] = []
    for anchor in root.iter("a"):
        href = anchor.get("href") or ""
        if "info/" not in href:
            continue
        raw = " ".join("".join(anchor.itertext()).replace("​", " ").split())
        category_match = _CATEGORY_RE.match(raw)
        title = _CATEGORY_RE.sub("", raw).strip()
        if len(title) < 4:
            continue
        link = urljoin(response.url, href)
        if link in seen:
            continue
        # 没年份就没法和别的站一起按时间排，猜年份会把老通知显示成今年：不收，记一笔
        date_match = _DATE_RE.search(_row_text(anchor))
        if date_match is None:
            undated += 1
            continue
        try:
            date = datetime.date(*(int(part) for part in date_match.groups()))
        except ValueError:
            undated += 1
            continue
        # 置顶占位会写成 2099-12-31 之类的未来日期，不是真通知
        if date > latest:
            continue
        seen.add(link)
        tags = [category_match.group(1)] if category_match else []
        items.append(Notification(title, link, source.id, tags=tags, date=date))
    has_more = bool(root.xpath(f'//a[contains(@href, "currentnum={page + 1}")]'))
    return items, has_more, undated


def _search_list(source: SourceDescriptor, keyword: str, pages: int) -> list[Notification]:
    terms = [term.casefold() for term in keyword.split() if term]
    notifications = create_crawler(source.id, pages).get_notifications()
    return [n for n in notifications if all(term in n.title.casefold() for term in terms)]


def search_source(source_id: str, keyword: str, pages: int = 2) -> list[Notification]:
    """在一个来源里搜 ``keyword``，最多翻 ``pages`` 页，按日期倒序。"""
    keyword = keyword.strip()
    if not keyword:
        return []
    source = source_registry.require(source_id)
    found: dict[str, Notification] = {}
    action = None
    session = None
    if source.crawler == "generic":
        session = _session_for(source)
        action = _action_for(session, source)
    if action is None:
        results = _search_list(source, keyword, pages)
    else:
        results = []
        for page in range(1, max(1, pages) + 1):
            items, has_more, undated = _search_vsb(session, source, action, keyword, page)
            # 这个站的检索结果不带完整日期：没法按时间排，改用列表本地筛
            if page == 1 and not items and undated > 0:
                results = _search_list(source, keyword, pages)
                break
            results.extend(items)
            if not has_more:
                break
    for notification in results:
        found.setdefault(notification.link, notification)
    return sorted(found.values(), key=lambda n: n.date, reverse=True)


def search(source_ids: Iterable[str], keyword: str, pages: int = 2) -> SiteSearchResult:
    """多个来源并发搜，合并去重、按日期倒序；失败的来源记进 errors。"""
    ids = [source_id for source_id in source_ids if source_registry.get(source_id) is not None]
    result = SiteSearchResult([])
    if not ids or not keyword.strip():
        return result

    def run(source_id: str):
        try:
            return source_id, search_source(source_id, keyword, pages), None
        except Exception as error:  # 单个来源失败不影响其他来源
            return source_id, [], f"{type(error).__name__}: {error}"

    merged: dict[str, Notification] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as pool:
        for source_id, items, error in pool.map(run, ids):
            if error is not None:
                result.errors[source_id] = error
            for notification in items:
                merged.setdefault(notification.link, notification)
    result.notifications = sorted(merged.values(), key=lambda n: n.date, reverse=True)
    return result
