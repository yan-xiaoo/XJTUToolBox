from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .portal import follow_login_chain, needs_login


SSNO_RE = re.compile(r"jiaocai1\.lib\.xjtu\.edu\.cn[^\"']*[?&]ssno=(\d+)|goRead\?ssno=(\d+)")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class JiaocaiBook:
    book_id: str
    app_id: int
    engine_instance_id: int
    title: str
    author: str
    summary: str
    ssno: str = ""


class JiaocaiCatalog:
    BASE = "https://jiaocai.lib.xjtu.edu.cn"
    FID = "17071"
    PAGE_ID = "13858"
    SEARCH_ID = "10700"

    def __init__(self, session: requests.Session):
        self.session = session

    def _get(self, url: str) -> str:
        response = self.session.get(
            url,
            headers={"Referer": f"{self.BASE}/", "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
        )
        body = response.text
        if needs_login(body):
            follow_login_chain(self.session, body)
            body = self.session.get(
                url,
                headers={"Referer": f"{self.BASE}/", "X-Requested-With": "XMLHttpRequest"},
                timeout=20,
            ).text
        return body

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[JiaocaiBook]:
        url = (
            f"{self.BASE}/engine2/search/search-list"
            f"?wfwfid={self.FID}&keyWord={quote(keyword)}"
            f"&pageIndex={page}&pageSize={page_size}"
            f"&pageId={self.PAGE_ID}&searchStrategy=0&searchId={self.SEARCH_ID}"
        )
        try:
            payload = __import__("json").loads(self._get(url))
        except ValueError:
            return []
        books = []
        for item in ((payload.get("data") or {}).get("dataList") or []):
            raw = str(item.get("content") or "")
            match = SSNO_RE.search(raw)
            books.append(JiaocaiBook(
                book_id=str(item.get("id") or ""),
                app_id=int(item.get("appId") or 0),
                engine_instance_id=int(item.get("engineInstanceId") or 0),
                title=TAG_RE.sub("", str(item.get("title") or "")),
                author=str(item.get("author") or ""),
                summary=TAG_RE.sub("", raw),
                ssno=(match.group(1) or match.group(2)) if match else "",
            ))
        return books

    def fetch_ssno(self, book: JiaocaiBook) -> str:
        if book.ssno:
            return book.ssno
        numeric_id = book.book_id.rsplit("_", 1)[-1]
        if not numeric_id:
            return ""
        html = self._get(
            f"{self.BASE}/engine2/d/{numeric_id}/{book.engine_instance_id}/0/{book.app_id}"
            f"?pageId={self.PAGE_ID}&engineInstanceId={book.engine_instance_id}"
        )
        match = SSNO_RE.search(html)
        if match:
            book.ssno = match.group(1) or match.group(2)
        return book.ssno
