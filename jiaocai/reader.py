from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Iterable

import requests

from .portal import decode_smart, follow_login_chain, needs_login


BASE = "https://jiaocai1.lib.xjtu.edu.cn"
GUAJIE_BASE = "http://jiaocai1.lib.xjtu.edu.cn:9088"
CHANNEL = "100"
PREFIXES = ["cov", "bok", "leg", "fow", "!", "", "att", "cov"]
TYPE_NAMES = ["封面", "书名页", "版权页", "前言", "目录", "正文", "附录", "封底"]
LI_RE = re.compile(r"<li>(.*?)</li>", re.S)
SSNO_RE = re.compile(r"goRead\?ssno=(\d+)")
TITLE_RE = re.compile(r'<a[^>]*title="([^"]*)"')
COVER_RE = re.compile(r'<img[^>]*\ssrc="([^"]+)"')
DD_RE = re.compile(r"<dd>(.*?)</dd>", re.S)
JPG_PATH_RE = re.compile(r'jpgPath:\s*"([^"]+)"')
PAGES_RE = re.compile(r"var\s+pages\s*=\s*(\[\[.*?]]);")
PAIR_RE = re.compile(r"\[\s*(-?\d+)\s*,\s*(-?\d+)\s*]")
BOOK_PAGES_RE = re.compile(r"var\s+bookPages\s*=\s*(\d+)")
HEAD_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Jiaocai1Book:
    ssno: str
    title: str
    author: str = ""
    publish_date: str = ""
    theme: str = ""
    call_no: str = ""
    cover_url: str = ""


@dataclass
class Jiaocai1SearchResult:
    books: list[Jiaocai1Book] = field(default_factory=list)
    total_rows: int = 0
    current_page: int = 1
    total_pages: int = 1


@dataclass
class Jiaocai1Page:
    index: int
    type_index: int
    num_in_type: int
    file_name: str

    @property
    def type_name(self) -> str:
        return TYPE_NAMES[self.type_index]

    @property
    def label(self) -> str:
        if self.type_index == 5:
            return f"第 {self.num_in_type} 页"
        if self.type_index in {0, 1, 2, 7}:
            return self.type_name
        return f"{self.type_name} {self.num_in_type}"


@dataclass
class Jiaocai1Handle:
    ssno: str
    title: str
    jpg_path: str
    pages: list[Jiaocai1Page]


def file_name(num_in_type: int, type_index: int) -> str:
    prefix = PREFIXES[type_index]
    digits = str(num_in_type)
    pad = max(0, 6 - len(prefix) - len(digits))
    return prefix + ("0" * pad) + digits


def section_starts(pages: list[Jiaocai1Page]) -> list[tuple[str, int]]:
    """各页型首页在线性页表里的下标，用于跳章。"""
    starts: list[tuple[str, int]] = []
    seen: set[int] = set()
    for page in pages:
        if page.type_index in seen:
            continue
        seen.add(page.type_index)
        starts.append((page.type_name, page.index))
    return starts


def flatten(ranges: Iterable[tuple[int, int]]) -> list[Jiaocai1Page]:
    pages = []
    for type_index, (start, end) in enumerate(ranges):
        if start > end or start <= 0:
            continue
        for number in range(start, end + 1):
            pages.append(Jiaocai1Page(len(pages), type_index, number, file_name(number, type_index)))
    return pages


class Jiaocai1Reader:
    def __init__(self, session: requests.Session):
        self.session = session

    def _request(self, method: str, url: str, **kwargs) -> str:
        kwargs.setdefault("timeout", 20)
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("Referer", f"{BASE}/front/")
        headers.setdefault("X-Requested-With", "XMLHttpRequest")
        response = self.session.request(method, url, headers=headers, **kwargs)
        body = decode_smart(response.content)
        if needs_login(body):
            follow_login_chain(self.session, body)
            response = self.session.request(method, url, headers=headers, **kwargs)
            body = decode_smart(response.content)
        return body

    def search(self, keyword: str, field: str = "bookName", page: int = 1, cls: str = "") -> Jiaocai1SearchResult:
        data = {
            "cpage": str(page),
            "stype": "1",
            "orderField": "0",
            "sw": keyword,
            "searchField": field,
        }
        if cls:
            data["cls"] = cls
        html = self._request(
            "POST",
            f"{BASE}/front/book/search/index",
            data=data,
            headers={"Referer": f"{BASE}/front/book/search/page"},
        )
        books = []
        for match in LI_RE.finditer(html):
            block = match.group(1)
            ssno_match = SSNO_RE.search(block)
            if not ssno_match:
                continue
            fields = {}
            for dd in DD_RE.finditer(block):
                text = unescape(TAG_RE.sub("", dd.group(1))).strip()
                if "：" in text:
                    key, value = text.split("：", 1)
                    fields[key.strip()] = value.strip()
            books.append(Jiaocai1Book(
                ssno=ssno_match.group(1),
                title=unescape(TITLE_RE.search(block).group(1)).strip() if TITLE_RE.search(block) else "",
                author=fields.get("作者", ""),
                publish_date=fields.get("出版日期", ""),
                theme=fields.get("主题词", ""),
                call_no=fields.get("索书号", ""),
                cover_url=unescape(COVER_RE.search(block).group(1)) if COVER_RE.search(block) else "",
            ))
        current = int(re.search(r'data-cpage="(\d+)"', html).group(1)) if re.search(r'data-cpage="(\d+)"', html) else page
        total_pages = int(re.search(r'data-sum-page="(\d+)"', html).group(1)) if re.search(r'data-sum-page="(\d+)"', html) else 1
        total_rows = int(re.search(r'data-totalrow="(\d+)"', html).group(1)) if re.search(r'data-totalrow="(\d+)"', html) else len(books)
        return Jiaocai1SearchResult(books, total_rows, current, total_pages)

    def open_book(self, ssno: str) -> Jiaocai1Handle | None:
        handle = self._parse_reader(ssno, self._request("GET", f"{BASE}/front/reader/goRead?ssno={ssno}&channel={CHANNEL}&jpgread=1"))
        if handle:
            return handle
        try:
            return self._parse_reader(ssno, self._request("GET", f"{GUAJIE_BASE}/guajie/common?ssno={ssno}&cpage=1&channel={CHANNEL}"))
        except requests.RequestException:
            return None

    def _parse_reader(self, ssno: str, html: str) -> Jiaocai1Handle | None:
        jpg = JPG_PATH_RE.search(html)
        pages_raw = PAGES_RE.search(html)
        if not jpg or not pages_raw:
            return None
        ranges = [(int(a), int(b)) for a, b in PAIR_RE.findall(pages_raw.group(1))]
        if len(ranges) != 8:
            return None
        title_match = HEAD_TITLE_RE.search(html)
        return Jiaocai1Handle(
            ssno=ssno,
            title=unescape(title_match.group(1)).strip() if title_match else "",
            jpg_path=jpg.group(1),
            pages=flatten(ranges),
        )

    def page_url(self, handle: Jiaocai1Handle, page: Jiaocai1Page) -> str:
        return f"{BASE}/jpath/{handle.jpg_path}{page.file_name}.jpg?zoom=0"

    def fetch_page(self, handle: Jiaocai1Handle, page: Jiaocai1Page) -> bytes:
        url = self.page_url(handle, page)
        response = self.session.get(
            url,
            headers={"Referer": f"{BASE}/jpath/reader/reader.shtml"},
            timeout=30,
        )
        if response.status_code != 200 or not response.content:
            response = self.session.get(url, timeout=30)
        return response.content
