"""站内搜索：用各站自己的全文检索，而不是只在已经抓到的通知里筛。

本地筛只能在「已经抓到的那一两页」里找，半年前的通知永远搜不到；站内搜索查的是全站索引。

- 学院 / 部门站几乎都是博达 CMS，首页有个 ``search.jsp``（有的站叫 ``ssjgy.jsp``、``sou.jsp``）
  的全文检索表单。关键词 Base64 后放进 ``newskeycode2``，GET 就能翻页；每页约 15 条，每条带日期。
  结果按相关度排，旧通知常排在前面，所以取前两页再按日期倒序。
- 检索的是全站索引，结果不属于哪个频道：同一站点只搜一次，再按文章链接 ``info/<栏目id>/`` 归到
  订阅的频道（栏目 id 从频道列表里的通知链接学来），归不到已订阅频道的丢掉。
- 首页找不到检索表单、检索结果不带完整日期、或学不到频道栏目的，退回「抓列表前两页、本地按标题筛」。
"""

from __future__ import annotations

import base64
import datetime
import queue
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin, urlparse

from lxml import etree

from .crawlers import create_crawler
from .crawlers.crawler import get_session, pass_challenge_for_website
from .notification import Notification
from .source import SourceDescriptor, source_registry

_DATE_RE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
_CATEGORY_RE = re.compile(r"^\s*[\[【]([^\]】]{1,12})[\]】]\s*")
_COLUMN_RE = re.compile(r"(?:^|/)info/(\d+)/")
_TIMEOUT = 20
_WORKERS = 8

# 检索入口按站点首页缓存，空串表示这个站没有博达检索；频道栏目 id 按来源缓存。
_actions: dict[str, str] = {}
_columns: dict[str, frozenset[str]] = {}
_cache_lock = threading.Lock()


class SearchCancelled(Exception):
    """用户取消了站内搜索。"""


@dataclass
class SiteSearchResult:
    notifications: list[Notification]
    errors: dict[str, str] = field(default_factory=dict)


def column_of(link: str) -> str | None:
    """博达文章链接 ``…/info/1146/12345.htm`` 里的栏目 id。"""
    match = _COLUMN_RE.search(urlparse(link).path)
    return match.group(1) if match else None


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise SearchCancelled


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _home(source: SourceDescriptor) -> str:
    return source.home or f"{_origin(source.url)}/"


def _session_for(source: SourceDescriptor):
    if not source.needs_challenge:
        return get_session()
    origin = _origin(source.url)
    return pass_challenge_for_website(source.url, f"{origin}/dynamic_challenge")


def _action_for(session, source: SourceDescriptor, cancel: threading.Event) -> str | None:
    """站点首页上博达检索表单的绝对 action，没有返回 None。"""
    home = _home(source)
    with _cache_lock:
        if home in _actions:
            return _actions[home] or None
    _check(cancel)
    try:
        response = session.get(home, timeout=_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return None  # 首页都打不开：不缓存结论，下次再试
    root = etree.HTML(response.content, parser=etree.HTMLParser(recover=True))
    action = ""
    # 只认带博达检索字段的表单，别把登录框之类的 jsp 当成搜索
    for form in root.iter("form") if root is not None else ():
        target = form.get("action") or ""
        if ".jsp" in target and "wbtreeid=" in target and form.xpath(".//input[starts-with(@name, 'lucenenewssearchkey')]"):
            action = urljoin(response.url, target)
            break
    with _cache_lock:
        _actions[home] = action
    return action or None


def _row_date(anchor) -> datetime.date | None:
    """从链接往外逐层找日期，直到外层包住了别的通知链接为止（那已是整段列表，日期不是这条的）。"""
    title = "".join(anchor.itertext())
    node = anchor.getparent()
    while node is not None and isinstance(node.tag, str) and node.tag.lower() not in ("body", "html"):
        links = {a.get("href") for a in node.iter("a") if "info/" in (a.get("href") or "")}
        if len(links) > 1:
            return None
        # 去掉标题再找：标题里的「2025年1月20日放假」不是发布日期
        text = "".join(node.itertext())
        match = _DATE_RE.search(text.replace(title, " ") if title else text)
        if match:
            try:
                return datetime.date(*(int(part) for part in match.groups()))
            except ValueError:
                return None
        node = node.getparent()
    return None


def _search_vsb(session, source: SourceDescriptor, action: str, keyword: str, page: int):
    """返回 (通知列表, 是否还有下一页, 搜到但没有完整日期的条数)；通知暂记在 source 名下，之后再归属。"""
    key = base64.b64encode(keyword.encode("utf-8")).decode("ascii")
    url = f"{action}&searchScope=0&currentnum={page}&newskeycode2={quote(key, safe='')}"
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
        date = _row_date(anchor)
        if date is None:
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


def _search_list(source: SourceDescriptor, keyword: str, pages: int, cancel: threading.Event) -> list[Notification]:
    _check(cancel)
    terms = [term.casefold() for term in keyword.split() if term]
    notifications = create_crawler(source.id, pages).get_notifications()
    return [n for n in notifications if all(term in n.title.casefold() for term in terms)]


def _columns_for(source: SourceDescriptor, known_links: Iterable[str], cancel: threading.Event) -> frozenset[str]:
    """频道列表里的通知都在哪些栏目下：优先用本地已抓到的链接，没有就抓列表第一页。学不到给空集。"""
    with _cache_lock:
        learned = set(_columns.get(source.id, ()))
    learned.update(filter(None, map(column_of, known_links)))
    if not learned:
        _check(cancel)
        try:
            learned.update(filter(None, (column_of(n.link) for n in create_crawler(source.id, 1).get_notifications())))
        except Exception:
            return frozenset()
    result = frozenset(learned)
    with _cache_lock:
        _columns[source.id] = result
    return result


def _search_site(sources: list[SourceDescriptor], keyword: str, pages: int,
                 known: dict[str, list[str]], cancel: threading.Event) -> SiteSearchResult:
    """同一站点的几个频道：站内检索只跑一次，结果按栏目归到频道；归不了的频道退回列表筛。"""
    first = sources[0]
    _check(cancel)
    session = _session_for(first) if first.crawler == "generic" else None
    action = _action_for(session, first, cancel) if session is not None else None
    result = SiteSearchResult([])
    hits: list[Notification] | None = None
    if action is not None:
        hits = []
        for page in range(1, max(1, pages) + 1):
            _check(cancel)
            try:
                items, has_more, undated = _search_vsb(session, first, action, keyword, page)
            except SearchCancelled:
                raise
            except Exception as error:
                if page == 1:
                    raise
                label = f"{first.site_name or first.id} / 第 {page} 页"
                result.errors[label] = f"{type(error).__name__}: {error}"
                break
            # 这个站的检索结果不带完整日期：没法按时间排，改用列表本地筛
            if page == 1 and not items and undated > 0:
                hits = None
                break
            hits.extend(items)
            if not has_more:
                break

    columns = {s.id: _columns_for(s, known.get(s.id, ()), cancel) for s in sources} if hits is not None else {}
    for hit in hits or ():
        column = column_of(hit.link)
        owners = [s for s in sources if column in columns[s.id]]
        if not owners:
            continue  # 站内其他没订阅的栏目
        # 父栏目和子栏目都能认领时归给更具体（栏目更少）的那个
        owner = min(owners, key=lambda s: len(columns[s.id]))
        result.notifications.append(Notification(
            hit.title, hit.link, owner.id, tags=hit.tags.union(owner.tags), date=hit.date,
        ))
    for source in sources:
        if hits is None or not columns[source.id]:
            try:
                result.notifications.extend(_search_list(source, keyword, pages, cancel))
            except SearchCancelled:
                raise
            except Exception as error:
                label = f"{source.site_name} / {source.id}" if source.site_name else source.id
                result.errors[label] = f"{type(error).__name__}: {error}"
    return result


def _run_parallel(tasks: list[tuple[str, Callable[[], SiteSearchResult]]], cancel: threading.Event):
    """用守护线程并发跑；取消时立刻返回，在途请求留给守护线程自生自灭，不拖住程序退出。"""
    pending: queue.Queue = queue.Queue()
    for task in tasks:
        pending.put(task)
    done: queue.Queue = queue.Queue()

    def worker() -> None:
        while not cancel.is_set():
            try:
                key, job = pending.get_nowait()
            except queue.Empty:
                return
            try:
                done.put(job())
            except SearchCancelled:
                return
            except Exception as error:  # 单个站点失败不影响其他站点
                done.put(SiteSearchResult([], {key: f"{type(error).__name__}: {error}"}))

    for _ in range(min(_WORKERS, len(tasks))):
        threading.Thread(target=worker, name="site-search", daemon=True).start()
    finished = []
    while len(finished) < len(tasks):
        _check(cancel)
        try:
            finished.append(done.get(timeout=0.1))
        except queue.Empty:
            continue
    _check(cancel)
    return finished


def search(source_ids: Iterable[str], keyword: str, pages: int = 2, *,
           known: Iterable[tuple[str, str]] = (),
           accept: Callable[[Notification], bool] | None = None,
           cancel: threading.Event | None = None) -> SiteSearchResult:
    """
    在订阅的来源里搜 ``keyword``，合并去重、按日期倒序；失败的站点或频道记进 errors。

    :param known: 本地已有通知的 (来源, 链接)，用来学各频道的栏目 id，省得再抓列表。
    :param accept: 二次过滤，一般传 ``NotificationManager.satisfy_filter``，让用户的规则照样生效。
    :param cancel: 置位后尽快抛 ``SearchCancelled``。
    """
    cancel = cancel or threading.Event()
    result = SiteSearchResult([])
    keyword = keyword.strip()
    sources = [one for one in map(source_registry.get, source_ids) if one is not None]
    if not sources or not keyword:
        return result
    known_links: dict[str, list[str]] = {}
    for source_id, link in known:
        known_links.setdefault(source_id, []).append(link)
    sites: dict[str, list[SourceDescriptor]] = {}
    for source in sources:
        sites.setdefault(urlparse(_home(source)).netloc, []).append(source)

    tasks = [
        (group[0].site_name or group[0].id,
         lambda group=group: _search_site(group, keyword, pages, known_links, cancel))
        for group in sites.values()
    ]
    merged: dict[str, Notification] = {}
    for site_result in _run_parallel(tasks, cancel):
        result.errors.update(site_result.errors)
        for notification in site_result.notifications:
            if accept is None or accept(notification):
                merged.setdefault(notification.link, notification)
    result.notifications = sorted(merged.values(), key=lambda n: n.date, reverse=True)
    return result
