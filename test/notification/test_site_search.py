import base64
import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from notification import Notification
from notification import site_search
from notification.source import source_registry

TEST_DOMAIN = "notification-crawler"

HOME = (
    '<html><body><form action="/search.jsp?wbtreeid=1001" method="post">'
    '<input name="lucenenewssearchkey"></form></body></html>'
)
RESULTS = (
    "<html><head><meta charset=\"utf-8\"></head><body><ul>"
    "<li><a href='info/1001/1.htm'>[通知]关于奖学金评定的通知</a><span>2025-03-01</span></li>"
    "<li><a href='info/1001/2.htm'>关于奖学金答辩安排</a><span>2026-01-10</span></li>"
    "<li><a href='info/1001/3.htm'>没有日期的奖学金结果</a></li>"
    "</ul></body></html>"
)


class FakeSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        body = RESULTS if "search.jsp" in url else HOME
        return SimpleNamespace(
            content=body.encode("utf-8"), encoding="utf-8", url=url, raise_for_status=lambda: None,
        )


def _generic_source():
    for source in source_registry.all() if hasattr(source_registry, "all") else source_registry:
        if source.crawler == "generic" and not source.needs_challenge:
            return source
    raise unittest.SkipTest("没有可用的 generic 来源")


class SiteSearchTest(unittest.TestCase):
    def setUp(self):
        site_search._actions.clear()

    def test_vsb_search_encodes_keyword_and_sorts_by_date(self):
        source = _generic_source()
        session = FakeSession()
        with patch.object(site_search, "get_session", return_value=session):
            results = site_search.search_source(source.id, "奖学金", pages=1)

        self.assertEqual([n.title for n in results], ["关于奖学金答辩安排", "关于奖学金评定的通知"])
        self.assertEqual(results[0].date, datetime.date(2026, 1, 10))
        key = base64.b64encode("奖学金".encode("utf-8")).decode("ascii")
        self.assertTrue(any("search.jsp?wbtreeid=1001" in url and "newskeycode2=" in url for url in session.urls))
        self.assertTrue(any(key.replace("=", "%3D") in url for url in session.urls))

    def test_search_action_is_cached_per_origin(self):
        source = _generic_source()
        session = FakeSession()
        with patch.object(site_search, "get_session", return_value=session):
            site_search.search_source(source.id, "奖学金", pages=1)
            site_search.search_source(source.id, "答辩", pages=1)
        homepage_hits = [url for url in session.urls if "search.jsp" not in url]
        self.assertEqual(len(homepage_hits), 1)

    def test_one_failing_source_does_not_hide_others(self):
        notice = Notification(title="好结果", link="https://example.com/info/1.htm", source="x",
                              date=datetime.date(2026, 1, 1))

        def fake(source_id, keyword, pages):
            if source_id == "bad":
                raise RuntimeError("boom")
            return [notice]

        with patch.object(site_search, "search_source", side_effect=fake), \
                patch.object(site_search.source_registry, "get", return_value=object()):
            result = site_search.search(["good", "bad"], "结果")

        self.assertEqual(result.notifications, [notice])
        self.assertIn("bad", result.errors)

    def test_blank_keyword_returns_nothing(self):
        self.assertEqual(site_search.search(["anything"], "   ").notifications, [])


if __name__ == "__main__":
    unittest.main()
