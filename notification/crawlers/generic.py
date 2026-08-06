"""Data-driven crawlers used by the notification source registry."""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from lxml import etree

from notification.notification import Notification
from notification.source import SourceDescriptor, source_registry

from .crawler import Crawler, get_session, pass_challenge_for_website


_FULL_DATE = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)")
_DAY_YEAR_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(20\d{2})[-/.年](\d{1,2})(?:月)?(?!\d)")
_YEAR_MONTH = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})(?:月)?(?!\d)")
_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)")
_MONTH_DAY_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?:\s*,\s*|\s+)(20\d{2})(?!\d)"
)
_YEAR = re.compile(r"^20\d{2}$")
_DAY = re.compile(r"^(?:0?[1-9]|[12]\d|3[01])$")
_ENGLISH_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_ENGLISH_MONTH_PATTERN = "|".join(
    sorted((re.escape(one) for one in _ENGLISH_MONTHS), key=len, reverse=True)
)
_ENGLISH_DATE_PATTERNS = (
    re.compile(
        rf"(?<![A-Za-z0-9])(?P<day>\d{{1,2}})\s+"
        rf"(?P<month>{_ENGLISH_MONTH_PATTERN})\s+(?P<year>20\d{{2}})(?!\d)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<![A-Za-z0-9])(?P<month>{_ENGLISH_MONTH_PATTERN})\s+"
        rf"(?P<day>\d{{1,2}})\s+(?P<year>20\d{{2}})(?!\d)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class _NotificationCandidate:
    """A list item before an optional detail-page date is resolved."""

    title: str
    link: str
    date: datetime.date | None
    tags: frozenset[str]


def _clean_text(value: object) -> str:
    return " ".join(str(value).replace("\xa0", " ").split())


def parse_publication_date(values: Iterable[object]) -> datetime.date | None:
    """Parse numeric, English, and split CMS date representations."""

    texts = [_clean_text(value) for value in values if _clean_text(value)]
    joined = " ".join(texts)

    match = _FULL_DATE.search(joined)
    if match:
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            pass

    # Some XJTU templates render the day before the year-month, for example
    # ``30 / 2026-07`` on the Milan joint-school announcement page.
    match = _DAY_YEAR_MONTH.search(joined)
    if match:
        day, year, month = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            pass

    # ISO timestamps are common in <time datetime="..."></time>.
    iso_match = re.search(r"(?<!\d)(20\d{2}-\d{2}-\d{2})[T\s]", joined)
    if iso_match:
        try:
            return datetime.date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass

    # XJTU pages use month/day ordering when a slash date is followed by a
    # separate year (for example ``08/03 2026``).  Parse it explicitly instead
    # of relying on the process locale's numeric date conventions.
    match = _MONTH_DAY_YEAR.search(joined)
    if match:
        month, day, year = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            pass

    english = re.sub(r"[,|]", " ", joined)
    english = _clean_text(english)
    # ``datetime.strptime(..., "%b")`` follows LC_TIME.  Qt can change that
    # process-global locale while constructing QApplication, so use a static
    # ASCII month table and never mutate or depend on global locale state.
    for pattern in _ENGLISH_DATE_PATTERNS:
        match = pattern.search(english)
        if match:
            month = _ENGLISH_MONTHS[match.group("month").casefold()]
            try:
                return datetime.date(
                    int(match.group("year")), month, int(match.group("day"))
                )
            except ValueError:
                continue

    year_months: list[tuple[int, int]] = []
    month_days: list[tuple[int, int]] = []
    years: list[int] = []
    days: list[int] = []
    for text in texts:
        ym = _YEAR_MONTH.fullmatch(text)
        if ym:
            year_months.append((int(ym.group(1)), int(ym.group(2))))
        md = _MONTH_DAY.fullmatch(text)
        if md:
            month_days.append((int(md.group(1)), int(md.group(2))))
        if _YEAR.fullmatch(text):
            years.append(int(text))
        if _DAY.fullmatch(text):
            days.append(int(text))

    for (year, month) in year_months:
        for day in days:
            try:
                return datetime.date(year, month, day)
            except ValueError:
                continue
    for (month, day) in month_days:
        for year in years:
            try:
                return datetime.date(year, month, day)
            except ValueError:
                continue
    return None


def _xpath_values(element, xpath: object | None) -> list[object]:
    if not xpath:
        return []
    if not isinstance(xpath, str):
        return []
    result = element.xpath(xpath)
    values: list[object] = []
    for value in result:
        if isinstance(value, etree._Element):
            values.append(_clean_text(" ".join(value.itertext())))
            for attribute in ("datetime", "content", "title"):
                if value.get(attribute):
                    values.append(value.get(attribute))
        else:
            values.append(value)
    return values


def _all_date_values(element) -> list[object]:
    values: list[object] = list(element.xpath(".//text()"))
    values.extend(element.xpath(".//@datetime | .//@content"))
    return values


def _find_link_and_title(element, selectors: dict[str, object]) -> tuple[str, str] | None:
    link_values = _xpath_values(element, selectors.get("link_xpath"))
    if link_values:
        link = _clean_text(link_values[0])
        anchor = None
    else:
        anchors = element.xpath(".//a[@href and not(starts-with(@href, 'javascript:'))]")
        anchor = next((one for one in anchors if one.get("href") not in ("", "#")), None)
        if anchor is None:
            return None
        link = anchor.get("href", "")

    title_values = _xpath_values(element, selectors.get("title_xpath"))
    if title_values:
        title = max((_clean_text(value) for value in title_values), key=len, default="")
    else:
        anchors = element.xpath(".//a[@href and not(starts-with(@href, 'javascript:'))]")
        # A non-empty title attribute is authoritative.  Do not compare it to
        # itertext() by length: XJTU variants A/C/D put the date inside <a>, so
        # the combined text is inevitably longer and would pollute the title.
        attribute_titles = [_clean_text(one.get("title", "")) for one in anchors]
        attribute_titles = [one for one in attribute_titles if one]
        if attribute_titles:
            title = max(attribute_titles, key=len)
        else:
            semantic_titles: list[str] = []
            for one in anchors:
                semantic_nodes = one.xpath(
                    ".//*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or "
                    "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'title') or "
                    "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'txt')]"
                )
                semantic_titles.extend(_clean_text(" ".join(node.itertext())) for node in semantic_nodes)
            semantic_titles = [one for one in semantic_titles if len(one) >= 4]
            if semantic_titles:
                title = max(semantic_titles, key=len)
            else:
                candidates: list[str] = []
                for one in anchors:
                    clean_parts = [
                        _clean_text(part)
                        for part in one.xpath(".//text()")
                        if _clean_text(part) and not _looks_like_date_fragment(_clean_text(part))
                    ]
                    candidates.append(_clean_text(" ".join(clean_parts)))
                title = max((one for one in candidates if one), key=len, default="")
    if len(title) < 4 or not link:
        return None
    return link, title


def _looks_like_date_fragment(text: str) -> bool:
    if _FULL_DATE.fullmatch(text) or _YEAR_MONTH.fullmatch(text) or _MONTH_DAY.fullmatch(text):
        return True
    if _YEAR.fullmatch(text) or _DAY.fullmatch(text):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        return True
    return parse_publication_date([text]) is not None


def _extract_candidate(
    element,
    source: SourceDescriptor,
    response_url: str,
) -> _NotificationCandidate | None:
    selectors = dict(source.selectors or {})
    link_title = _find_link_and_title(element, selectors)
    if link_title is None:
        return None
    link, title = link_title
    date_values = _xpath_values(element, selectors.get("date_xpath")) or _all_date_values(element)
    publication_date = parse_publication_date(date_values)
    # Undated navigation entries must never outvote a smaller, real notice
    # list.  Retain them only when the registry explicitly enables the generic
    # detail-page date fallback for this source.
    if publication_date is None and not selectors.get("detail_date_xpath"):
        return None
    tags = set(source.tags)
    tags.update(
        _clean_text(value).strip("[]【】")
        for value in element.xpath(".//i/text()")
        if _clean_text(value).strip("[]【】")
    )
    return _NotificationCandidate(
        title=title,
        link=urljoin(response_url, link),
        date=publication_date,
        tags=frozenset(tags),
    )


def _candidate_to_notification(
    candidate: _NotificationCandidate,
    source_id: str,
) -> Notification | None:
    if candidate.date is None:
        return None
    return Notification(
        title=candidate.title,
        link=candidate.link,
        source=source_id,
        date=candidate.date,
        tags=set(candidate.tags),
    )


def _deduplicate_candidates(
    candidates: Iterable[_NotificationCandidate],
) -> list[_NotificationCandidate]:
    result: list[_NotificationCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.title, candidate.link)
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def extract_html_notification_candidates(
    html: bytes | str,
    source: SourceDescriptor,
    response_url: str,
) -> list[_NotificationCandidate]:
    """Extract list items, retaining entries whose year lives on the detail page."""

    parser = etree.HTMLParser(recover=True)
    root = etree.HTML(html, parser=parser, base_url=response_url)
    if root is None:
        return []
    selectors = dict(source.selectors or {})
    item_xpath = selectors.get("item_xpath")
    if isinstance(item_xpath, str) and item_xpath:
        items = root.xpath(item_xpath)
        return _deduplicate_candidates(
            candidate
            for item in items
            if isinstance(item, etree._Element)
            for candidate in [_extract_candidate(item, source, response_url)]
            if candidate is not None
        )

    containers = root.xpath(
        "//ul | //ol | //table | //div["
        "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'list') or "
        "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'notice') or "
        "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'news')]"
    )
    best: list[_NotificationCandidate] = []
    for container in containers:
        items = container.xpath("./li | ./article | ./tr | ./tbody/tr | ./div")
        if len(items) < 2:
            items = container.xpath(".//li | .//article | .//tr")
        extracted = _deduplicate_candidates(
            candidate
            for item in items
            for candidate in [_extract_candidate(item, source, response_url)]
            if candidate is not None
        )
        if len(extracted) > len(best):
            best = extracted

    if best:
        return best

    fallback_items = root.xpath(
        "//li | //article | //tr | //div[contains(@class, 'item') or contains(@class, 'Item')]"
    )
    return _deduplicate_candidates(
        candidate
        for item in fallback_items
        for candidate in [_extract_candidate(item, source, response_url)]
        if candidate is not None
    )


def extract_html_notifications(html: bytes | str, source: SourceDescriptor, response_url: str) -> list[Notification]:
    """Extract one list page using configured XPath or XJTU CMS heuristics."""
    return _deduplicate(
        notification
        for candidate in extract_html_notification_candidates(html, source, response_url)
        for notification in [_candidate_to_notification(candidate, source.id)]
        if notification is not None
    )


def _deduplicate(notifications: Iterable[Notification]) -> list[Notification]:
    result: list[Notification] = []
    seen: set[tuple[str, str]] = set()
    for notification in notifications:
        key = (notification.title, notification.link)
        if key not in seen:
            result.append(notification)
            seen.add(key)
    return result


def _find_next_url(html: bytes | str, response_url: str, selectors: dict[str, object]) -> str | None:
    root = etree.HTML(html, parser=etree.HTMLParser(recover=True), base_url=response_url)
    if root is None:
        return None
    configured = _xpath_values(root, selectors.get("next_xpath"))
    if configured:
        next_url = urljoin(response_url, _clean_text(configured[0]))
        return next_url if _same_origin(response_url, next_url) else None
    anchors = root.xpath("//a[@href]")
    for anchor in anchors:
        text = _clean_text(" ".join(anchor.itertext())).lower()
        rel = _clean_text(anchor.get("rel", "")).lower()
        if rel == "next" or text in {"下页", "下一页", "next", "next page", ">", "›", "»"}:
            href = anchor.get("href", "")
            if href and not href.startswith("javascript:"):
                next_url = urljoin(response_url, href)
                return next_url if _same_origin(response_url, next_url) else None
    return None


def _extract_detail_date(
    html: bytes | str,
    response_url: str,
    detail_date_xpath: str,
) -> datetime.date | None:
    root = etree.HTML(
        html,
        parser=etree.HTMLParser(recover=True),
        base_url=response_url,
    )
    if root is None:
        return None
    return parse_publication_date(_xpath_values(root, detail_date_xpath))


def _positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _nonnegative_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 0), maximum)


def _same_origin(left: str, right: str) -> bool:
    left_url = urlparse(left)
    right_url = urlparse(right)
    try:
        left_port = left_url.port or (443 if left_url.scheme == "https" else 80)
        right_port = right_url.port or (443 if right_url.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        left_url.scheme.lower(),
        (left_url.hostname or "").lower(),
        left_port,
    ) == (
        right_url.scheme.lower(),
        (right_url.hostname or "").lower(),
        right_port,
    )


class GenericListCrawler(Crawler):
    """Crawler whose source and parsing behavior are supplied by the registry."""

    def __init__(self, source_id: str, pages: int = 1, timeout: int = 35, allow_unverified: bool = False):
        super().__init__(pages)
        self.source = source_registry.require(source_id)
        self.timeout = timeout
        self.allow_unverified = allow_unverified
        self.detail_errors: dict[str, str] = {}

    def _session(self):
        if not self.source.needs_challenge:
            return get_session()
        parsed = urlparse(self.source.url)
        challenge_url = f"{parsed.scheme}://{parsed.netloc}/dynamic_challenge"
        return pass_challenge_for_website(self.source.url, challenge_url)

    def get_notifications(self, clear_repeat: bool = True) -> list[Notification]:
        if not self.source.verified and not self.allow_unverified:
            if self.source.status == "empty":
                return []
            raise ValueError(f"通知源尚未通过抓取验证：{self.source.display_name}")
        if self.source.crawler == "rss":
            return self._get_rss()
        if self.source.crawler == "json":
            return self._get_json()

        session = self._session()
        url: str | None = self.source.url
        notifications: list[Notification] = []
        detail_dates: dict[str, datetime.date | None] = {}
        detail_requests = 0
        for _ in range(max(1, self.pages)):
            if not url:
                break
            response = session.get(url, timeout=self.timeout)
            response.raise_for_status()
            candidates = extract_html_notification_candidates(response.content, self.source, response.url)
            resolved, detail_requests = self._resolve_candidates(
                session,
                candidates,
                detail_dates,
                detail_requests,
            )
            notifications.extend(resolved)
            url = _find_next_url(response.content, response.url, dict(self.source.selectors or {}))
        return _deduplicate(notifications) if clear_repeat else notifications

    def _resolve_candidates(
        self,
        session,
        candidates: Sequence[_NotificationCandidate],
        detail_dates: dict[str, datetime.date | None],
        detail_requests: int,
    ) -> tuple[list[Notification], int]:
        selectors = dict(self.source.selectors or {})
        detail_date_xpath = selectors.get("detail_date_xpath")
        detail_limit = _positive_int(selectors.get("detail_date_max"), default=30, maximum=100)
        detail_retries = _nonnegative_int(selectors.get("detail_date_retries"), default=1, maximum=3)
        result: list[Notification] = []
        for candidate in _deduplicate_candidates(candidates):
            resolved = candidate
            if candidate.date is None and isinstance(detail_date_xpath, str) and detail_date_xpath:
                if not _same_origin(self.source.url, candidate.link):
                    self.detail_errors[candidate.link] = "detail page is outside the source origin"
                    continue
                if candidate.link not in detail_dates:
                    if detail_requests >= detail_limit:
                        self.detail_errors[candidate.link] = f"detail request limit reached ({detail_limit})"
                        continue
                    detail_requests += 1
                    for attempt in range(detail_retries + 1):
                        try:
                            response = session.get(candidate.link, timeout=self.timeout)
                            response.raise_for_status()
                            detail_dates[candidate.link] = _extract_detail_date(
                                response.content,
                                response.url,
                                detail_date_xpath,
                            )
                        except Exception as error:
                            if attempt < detail_retries:
                                continue
                            detail_dates[candidate.link] = None
                            self.detail_errors[candidate.link] = f"{type(error).__name__}: {error}"
                        break
                detail_date = detail_dates[candidate.link]
                if detail_date is not None:
                    resolved = _NotificationCandidate(
                        title=candidate.title,
                        link=candidate.link,
                        date=detail_date,
                        tags=candidate.tags,
                    )
                elif candidate.link not in self.detail_errors:
                    self.detail_errors[candidate.link] = "detail date did not match the configured selector"
            notification = _candidate_to_notification(resolved, self.source.id)
            if notification is not None:
                result.append(notification)
        return result, detail_requests

    def _get_rss(self) -> list[Notification]:
        response = get_session().get(self.source.url, timeout=self.timeout)
        response.raise_for_status()
        root = etree.fromstring(response.content, parser=etree.XMLParser(recover=True))
        notifications: list[Notification] = []
        for item in root.xpath("//*[local-name()='item'] | //*[local-name()='entry']"):
            title = _clean_text(" ".join(item.xpath("./*[local-name()='title']//text()")))
            links = item.xpath("./*[local-name()='link']/@href | ./*[local-name()='link']/text()")
            dates = item.xpath(
                "./*[local-name()='pubDate']/text() | ./*[local-name()='published']/text() | "
                "./*[local-name()='updated']/text()"
            )
            date = parse_publication_date(dates)
            if not title or not links or date is None:
                continue
            notifications.append(Notification(title, urljoin(response.url, links[0]), self.source.id, date=date, tags=self.source.tags))
        return _deduplicate(notifications)

    def _get_json(self) -> list[Notification]:
        notifications: list[Notification] = []
        selectors = dict(self.source.selectors or {})
        for page in range(1, max(1, self.pages) + 1):
            url = _replace_query_parameter(self.source.url, selectors.get("page_parameter", "page"), str(page))
            response = get_session().get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            items = payload
            for key in selectors.get("items_key", "items").split("."):
                items = items[key]
            for item in items:
                title = _clean_text(item.get(selectors.get("title_key", "title"), ""))
                link = _clean_text(item.get(selectors.get("link_key", "url"), ""))
                date = parse_publication_date([item.get(selectors.get("date_key", "date"), "")])
                if title and link and date is not None:
                    notifications.append(Notification(title, urljoin(response.url, link), self.source.id, date=date, tags=self.source.tags))
        return _deduplicate(notifications)


def _replace_query_parameter(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))
