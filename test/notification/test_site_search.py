import base64
import datetime
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from notification import Notification, NotificationManager
from notification import site_search
from notification.filter import TagIncludeFilter, TitleExcludeFilter
from notification.ruleset import Ruleset
from notification.source import source_registry

TEST_DOMAIN = "notification-crawler"

# 研究生院：招生工作 1145、培养工作 1146；二附院首页不在站点根目录
ZSGZ, PYGZ, XWGZ = "gs/zsgz", "gs/pygz", "gs/xwgz"
SECOND = "xjtu2h/bksjy"

HOME = (
    "<html><body>"
    '<form action="login.jsp?wbtreeid=1"><input name="username"></form>'
    '<form action="ssjgy.jsp?wbtreeid=1111" method="post">'
    '<input type="hidden" name="lucenenewssearchkeyword"><input name="showkeycode"></form>'
    "</body></html>"
)
RESULTS = (
    "<html><head><meta charset=\"utf-8\"></head><body><ul>"
    "<li><div class='title'><a href='info/1146/2.htm'>[通知]关于重修报名的通知</a></div><span>2026-01-10</span></li>"
    "<li><a href='info/1145/1.htm'>招生复试重修说明</a><span>2025-03-01</span></li>"
    "<li><a href='info/1230/3.htm'>新闻里提到重修的报道</a><span>2025-05-01</span></li>"
    "<li><a href='info/1146/4.htm'>2025年1月20日起重修缴费</a></li>"
    "</ul></body></html>"
)


class FakeSession:
    def __init__(self, home=HOME, results=RESULTS):
        self.urls = []
        self.home = home
        self.results = results

    def get(self, url, timeout=None):
        self.urls.append(url)
        body = self.results if "newskeycode2=" in url else self.home
        return SimpleNamespace(content=body.encode("utf-8"), encoding="utf-8", url=url, raise_for_status=lambda: None)


def _notice(source, link, title="已抓到的通知"):
    return Notification(title, link, source, date=datetime.date(2026, 1, 1))


class FakeCrawler:
    """按来源返回列表页通知；记录被抓了哪些来源。"""

    pages = {
        ZSGZ: [_notice(ZSGZ, "https://gs.xjtu.edu.cn/info/1145/9.htm")],
        PYGZ: [_notice(PYGZ, "https://gs.xjtu.edu.cn/info/1146/9.htm", "重修列表里的通知")],
        XWGZ: [_notice(XWGZ, "https://gs.xjtu.edu.cn/info/1148/9.htm")],
    }

    def __init__(self):
        self.crawled = []

    def __call__(self, source_id, pages):
        self.crawled.append(source_id)
        return SimpleNamespace(get_notifications=lambda: list(self.pages.get(source_id, [])))


class SiteSearchTest(unittest.TestCase):
    def setUp(self):
        site_search._actions.clear()
        site_search._columns.clear()
        self.session = FakeSession()
        self.crawler = FakeCrawler()
        patches = [
            patch.object(site_search, "_session_for", return_value=self.session),
            patch.object(site_search, "create_crawler", side_effect=self.crawler),
        ]
        for one in patches:
            one.start()
            self.addCleanup(one.stop)

    def _search_urls(self):
        return [url for url in self.session.urls if "newskeycode2=" in url]

    def test_one_search_per_site_and_results_go_to_their_own_channel(self):
        result = site_search.search([ZSGZ, PYGZ, XWGZ], "重修", pages=1)

        self.assertEqual(len(self._search_urls()), 1)
        self.assertEqual(
            [(n.source, n.link.rsplit("/", 2)[-2]) for n in result.notifications],
            [(PYGZ, "1146"), (ZSGZ, "1145")],
        )
        # 未订阅栏目 1230 的结果丢掉
        self.assertFalse(any("/1230/" in n.link for n in result.notifications))
        self.assertEqual(result.notifications[0].tags, {"通知", "培养工作"})
        key = quote(base64.b64encode("重修".encode("utf-8")).decode("ascii"), safe="")
        self.assertIn(f"https://gs.xjtu.edu.cn/ssjgy.jsp?wbtreeid=1111&searchScope=0&currentnum=1&newskeycode2={key}",
                      self.session.urls)

    def test_local_links_teach_columns_without_crawling(self):
        known = [(ZSGZ, "https://gs.xjtu.edu.cn/info/1145/8.htm"), (PYGZ, "https://gs.xjtu.edu.cn/info/1146/8.htm")]
        site_search.search([ZSGZ, PYGZ], "重修", pages=1, known=known)
        self.assertEqual(self.crawler.crawled, [])

    def test_unknown_columns_are_learned_once_by_crawling_the_list(self):
        site_search.search([ZSGZ, PYGZ], "重修", pages=1)
        site_search.search([ZSGZ, PYGZ], "复试", pages=1)
        self.assertEqual(sorted(self.crawler.crawled), [PYGZ, ZSGZ])
        self.assertEqual(len([u for u in self.session.urls if "newskeycode2=" not in u]), 1)

    def test_user_rules_filter_site_results_per_channel(self):
        manager = NotificationManager([ZSGZ, PYGZ], {PYGZ: [Ruleset(TitleExcludeFilter("报名"))]})
        result = site_search.search(manager.subscription, "重修", pages=1, accept=manager.satisfy_filter)
        self.assertEqual([n.title for n in result.notifications], ["招生复试重修说明"])

    def test_site_results_inherit_channel_tags_before_user_rules(self):
        manager = NotificationManager([PYGZ], {PYGZ: [Ruleset(TagIncludeFilter("培养工作"))]})
        result = site_search.search(manager.subscription, "重修", pages=1, accept=manager.satisfy_filter)

        self.assertEqual([n.tags for n in result.notifications], [{"通知", "培养工作"}])

    def test_failing_channel_fallback_preserves_other_channels_on_same_site(self):
        def create_crawler(source_id, pages):
            if source_id == PYGZ:
                raise RuntimeError("offline")
            return self.crawler(source_id, pages)

        known = [(ZSGZ, "https://gs.xjtu.edu.cn/info/1145/8.htm")]
        with patch.object(site_search, "create_crawler", side_effect=create_crawler):
            result = site_search.search([ZSGZ, PYGZ], "重修", pages=1, known=known)

        self.assertEqual([n.source for n in result.notifications], [ZSGZ])
        self.assertEqual(result.errors, {f"{source_registry.require(PYGZ).site_name} / {PYGZ}": "RuntimeError: offline"})

    def test_dates_found_outside_title_div_and_not_read_from_title(self):
        items, _, undated = site_search._search_vsb(
            self.session, source_registry.require(PYGZ), "https://gs.xjtu.edu.cn/ssjgy.jsp?wbtreeid=1111", "重修", 1)
        dates = {n.link.rsplit("/", 1)[-1]: n.date for n in items}
        self.assertEqual(dates["2.htm"], datetime.date(2026, 1, 10))
        # 标题里的「2025年1月20日」不是发布日期
        self.assertNotIn("4.htm", dates)
        self.assertEqual(undated, 1)

    def test_flat_list_does_not_borrow_first_date(self):
        flat = ("<div><a href='info/1146/1.htm'>第一条重修通知</a><span>2026-01-10</span>"
                "<a href='info/1146/2.htm'>第二条重修通知</a></div>")
        root = site_search.etree.HTML(flat)
        anchors = list(root.iter("a"))
        self.assertIsNone(site_search._row_date(anchors[1]))

    def test_form_action_with_path_resolves_against_home(self):
        home = ('<form action="search.jsp?wbtreeid=7" method="post">'
                '<input name="lucenenewssearchkeyword"></form>')
        self.session.home = home
        source = source_registry.require(SECOND)
        action = site_search._action_for(self.session, source, threading.Event())
        self.assertEqual(action, "http://www.2yuan.xjtu.edu.cn/defsyy/search.jsp?wbtreeid=7")
        self.assertEqual(self.session.urls, [source.home])

    def test_login_form_is_not_a_search_entry_and_falls_back_to_list(self):
        self.session.home = '<form action="login.jsp?wbtreeid=1"><input name="username"></form>'
        result = site_search.search([PYGZ], "重修", pages=1)
        self.assertEqual(self._search_urls(), [])
        self.assertEqual([n.title for n in result.notifications], ["重修列表里的通知"])

    def test_undated_results_fall_back_to_list(self):
        self.session.results = "<ul><li><a href='info/1146/1.htm'>没有日期的重修通知</a></li></ul>"
        result = site_search.search([PYGZ], "重修", pages=1)
        self.assertEqual([n.title for n in result.notifications], ["重修列表里的通知"])

    def test_one_failing_site_does_not_hide_others(self):
        good = _notice(PYGZ, "https://gs.xjtu.edu.cn/info/1146/1.htm")

        def fake(group, *args):
            if group[0].id == SECOND:
                raise RuntimeError("boom")
            return site_search.SiteSearchResult([good])

        with patch.object(site_search, "_search_site", side_effect=fake):
            result = site_search.search([PYGZ, SECOND], "结果")
        self.assertEqual(result.notifications, [good])
        self.assertEqual(list(result.errors), [source_registry.require(SECOND).site_name])

    def test_cancel_returns_without_waiting_for_slow_sites(self):
        cancel = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def slow(*args):
            release.wait(10)
            return site_search.SiteSearchResult([])

        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        with patch.object(site_search, "_search_site", side_effect=slow):
            with self.assertRaises(site_search.SearchCancelled):
                site_search.search([PYGZ, SECOND], "重修", cancel=cancel)
        self.assertLess(time.monotonic() - started, 2)

    def test_blank_keyword_returns_nothing(self):
        self.assertEqual(site_search.search([PYGZ], "   ").notifications, [])
        self.assertEqual(self.session.urls, [])


if __name__ == "__main__":
    unittest.main()
