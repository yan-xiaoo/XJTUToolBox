from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

# 教务处「校历」页面。one2020 的校历 JSON 接口（/EIP/schoolcalendar/terms.htm）目前
# 固定返回 {"code": 200, "data": []}，教务处改为在该页面以图片形式发布各学年校历。
CALENDAR_PAGE_URL = "https://dean.xjtu.edu.cn/xxfw/xl.htm"

# 任意标签（a/img/...）里的 href/title 属性
_HREF_ATTRIBUTE = re.compile(r"""href=["']([^"']+)["']""", re.I)
_TITLE_ATTRIBUTE = re.compile(r"""title=["']([^"']*)["']""", re.I)
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_IMAGE_URL = re.compile(r"\.(?:jpe?g|png)(?:\?|$)", re.I)
_YEAR = re.compile(r"(\d{4})-(\d{4})")


@dataclass(frozen=True)
class CalendarImage:
    """一张校历图片"""

    year: str | None  # 学年，例如 "2026-2027"；教务处没有标注学年的图片为 None
    url: str  # 图片的绝对地址

    @property
    def label(self) -> str:
        """下拉框中显示的文本"""
        return f"{self.year} 学年" if self.year else "未标注学年"


class SchoolCalendar:
    PAGE_URL = CALENDAR_PAGE_URL

    def __init__(self, session: requests.Session):
        self.session = session

    def get_calendar_images(self) -> list[CalendarImage]:
        """
        获取教务处校历页面上的校历图片，顺序与页面一致（新学年在前）。

        :raise requests.HTTPError: 如果请求出现错误
        """
        response = self.session.get(self.PAGE_URL, timeout=20)
        response.raise_for_status()
        return self.parse_calendar_images(response.text, self.PAGE_URL)

    @staticmethod
    def parse_calendar_images(html: str, page_url: str = CALENDAR_PAGE_URL) -> list[CalendarImage]:
        """
        解析校历页面。教务处把每张校历写成 <a href="图片"><img ...></a>，
        学年优先取锚点的 title（如 "2015-2016学年校历"），否则取图片文件名（如 2026-2027.jpg），
        两者都拿不到的再根据页面顺序推定。
        """
        images: list[CalendarImage] = []
        seen: set[str] = set()
        for attributes, inner in _ANCHOR.findall(html):
            href = _HREF_ATTRIBUTE.search(attributes)
            # 只保留真正内嵌了图片的锚点，跳过纯文字链接与空锚点
            if href is None or "<img" not in inner.lower():
                continue
            url = _https_url(urljoin(page_url, href.group(1)))
            if url in seen or not _IMAGE_URL.search(url):
                continue
            seen.add(url)
            title = _TITLE_ATTRIBUTE.search(attributes)
            images.append(CalendarImage(_extract_year(title.group(1) if title else "", url), url))
        return _infer_years(images)


def _extract_year(title: str, url: str) -> str | None:
    """从 title 或图片文件名里取学年"""
    file_name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    match = _YEAR.search(title) or _YEAR.search(file_name)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _shift_year(year: str, delta: int) -> str:
    """学年加减，如 _shift_year("2026-2027", -1) == "2025-2026"""
    start, end = year.split("-")
    return f"{int(start) + delta}-{int(end) + delta}"


def _infer_years(images: list[CalendarImage]) -> list[CalendarImage]:
    """
    教务处页面按学年倒序排列各张校历，所以可以用已知学年做锚点，按顺序补齐没有标注学年的图片：
    锚点之后的每一张依次减一年；遇到下一个已知学年时以它为准（重新对齐）。
    开头的若干张若还未知（最新的一届没有标注），再从后面第一个已知学年往前推。
    """
    resolved: list[str | None] = [image.year for image in images]

    expected = None
    for index, year in enumerate(resolved):
        if year is None:
            resolved[index] = expected
        expected = _shift_year(resolved[index], -1) if resolved[index] else None

    first_known = next((index for index, year in enumerate(resolved) if year), None)
    if first_known:
        for index in range(first_known - 1, -1, -1):
            resolved[index] = _shift_year(resolved[index + 1], 1)

    return [CalendarImage(year, image.url) for image, year in zip(images, resolved)]


def _https_url(url: str) -> str:
    """校历页面里混有 http://jwc.xjtu.edu.cn 的旧链接，统一升级为 https"""
    return "https://" + url[len("http://"):] if url.startswith("http://") else url
