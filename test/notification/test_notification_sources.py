import datetime
import json
import threading
import time
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from notification import Notification, NotificationManager, Ruleset, TagIncludeFilter
from notification.crawlers import crawler as crawler_module
from notification.crawlers.generic import (
    GenericListCrawler,
    _find_next_url,
    _same_origin,
    extract_html_notifications,
    parse_publication_date,
)
from notification.source import SourceRegistry, source_registry


class DateParserTest(unittest.TestCase):
    def test_supported_date_variants(self):
        self.assertEqual(parse_publication_date(["2026-07-31"]), datetime.date(2026, 7, 31))
        self.assertEqual(parse_publication_date(["15", "2026-06"]), datetime.date(2026, 6, 15))
        self.assertEqual(parse_publication_date(["01/25", "2026"]), datetime.date(2026, 1, 25))
        self.assertEqual(parse_publication_date(["03 Aug 2026"]), datetime.date(2026, 8, 3))
        self.assertEqual(parse_publication_date(["08/03 2026"]), datetime.date(2026, 8, 3))
        self.assertEqual(parse_publication_date(["2026-08-03T06:51:37Z"]), datetime.date(2026, 8, 3))
        self.assertEqual(parse_publication_date(["30", "/", "2026-07"]), datetime.date(2026, 7, 30))

    def test_generic_xjtu_dom_variants(self):
        source = source_registry.require("ee/tzgg")
        variants = [
            ("<ul><li><a href='/info/1.htm'><span>2026-07-31</span><h3>电气学院第一条测试通知</h3></a></li></ul>", "电气学院第一条测试通知"),
            ("<ul><li><span>2026-07-30</span><a href='/info/2.htm' title='材料学院第二条测试通知'>短标题</a></li></ul>", "材料学院第二条测试通知"),
            ("<ul><li><a href='/info/3.htm'><p class='time'><span>2026-07-29</span></p><p class='txt'>软件学院第三条测试通知</p></a></li></ul>", "软件学院第三条测试通知"),
            ("<ul><li><a href='/info/4.htm' title='管理学院第四条测试通知'><span>15</span><p>2026-06</p></a></li></ul>", "管理学院第四条测试通知"),
            ("<ul><li><a href='/info/5.htm' title='化工学院第五条测试通知'><span>01/25</span><p>2026</p></a></li></ul>", "化工学院第五条测试通知"),
        ]
        for html, expected_title in variants:
            with self.subTest(html=html):
                result = extract_html_notifications(html, source, "https://ee.xjtu.edu.cn/list.htm")
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0].link.startswith("https://ee.xjtu.edu.cn/"))
                self.assertEqual(result[0].title, expected_title)

    def test_large_undated_navigation_never_outvotes_real_notice_list(self):
        source = source_registry.require("ee/tzgg")
        navigation = "".join(
            f"<li><a href='/nav/{index}.htm'>导航栏目 {index}</a></li>"
            for index in range(30)
        )
        html = (
            f"<ul class='navigation'>{navigation}</ul>"
            "<ul class='notice-list'>"
            "<li><span>2026-08-01</span><a href='/info/real-1.htm' title='真实的第一条通知'>通知</a></li>"
            "<li><span>2026-07-31</span><a href='/info/real-2.htm' title='真实的第二条通知'>通知</a></li>"
            "</ul>"
        )
        result = extract_html_notifications(html, source, source.url)
        self.assertEqual([one.title for one in result], ["真实的第一条通知", "真实的第二条通知"])

    def test_pagination_never_leaves_origin_and_malformed_ports_are_safe(self):
        current = "https://ee.xjtu.edu.cn/list.htm"
        self.assertEqual(
            _find_next_url("<a rel='next' href='/list/2.htm'>下一页</a>", current, {}),
            "https://ee.xjtu.edu.cn/list/2.htm",
        )
        self.assertIsNone(
            _find_next_url("<a rel='next' href='https://outside.example/2.htm'>下一页</a>", current, {})
        )
        self.assertFalse(_same_origin(current, "https://ee.xjtu.edu.cn:bad/2.htm"))

    def test_qualified_source_specific_dom_variants(self):
        samples = {
            "sce/tzgg": (
                "<div class='article-list panel-body news'><ul>"
                "<a href='info/1.htm' title='继续教育测试通知'><li>继续教育测试通知<span>2026-08-03</span></li></a>"
                "</ul></div>",
                "继续教育测试通知",
                datetime.date(2026, 8, 3),
            ),
            "jsdi/xygg": (
                "<ul><li><a href='../info/2.htm' title='米兰学院测试通知'>"
                "<p class='date'><span>30</span>/ 2026-07</p><p class='title'>米兰学院测试通知</p>"
                "</a></li></ul>",
                "米兰学院测试通知",
                datetime.date(2026, 7, 30),
            ),
            "cy/tzgg": (
                "<ul><li><span class='date1'>2026/06<font><span>/</span>13</font></span>"
                "<a href='https://example.test/cy' title='仲英书院测试通知'>仲英书院测试通知</a></li></ul>",
                "仲英书院测试通知",
                datetime.date(2026, 6, 13),
            ),
            "sph/tzgg": (
                "<div class='ej_rightbot'><dd><a href='../info/3.htm' title='公卫学院测试通知'>"
                "公卫学院测试通知</a><span>[2026-06-25]</span></dd><dl>摘要</dl></div>",
                "公卫学院测试通知",
                datetime.date(2026, 6, 25),
            ),
            "med/tzgg": (
                "<div class='list2_con'><ul><li><span class='date3'>2026-07-31</span>"
                "<a href='info/4.htm' title='医学部测试通知'>医学部测试通知</a></li></ul></div>",
                "医学部测试通知",
                datetime.date(2026, 7, 31),
            ),
            "gjcnpt/jxyx": (
                "<ul><li class='wow fadeInUp'><a href='../../info/1133/1558.htm' title='储能平台教学测试通知'>"
                "<div class='tm'><span>08/29</span><span class='big'>2023</span></div>"
                "<div class='text'><h1>储能平台教学测试通知</h1></div></a></li></ul>",
                "储能平台教学测试通知",
                datetime.date(2023, 8, 29),
            ),
            "xjtu2h/bksjy": (
                "<ul class='lb-list'><li><a href='../info/12661/499011.htm' "
                "title='第二临床医学院本科测试通知'>第二临床医学院本科测试通知"
                "<span>2026-07-19</span></a></li></ul>",
                "第二临床医学院本科测试通知",
                datetime.date(2026, 7, 19),
            ),
            "dental/yjsjy": (
                "<ul class='nt4'><li><a href='../info/1031/64082.htm'>"
                "<h4>口腔医学院研究生测试通知</h4><h6>2026-07-12</h6>"
                "</a></li></ul>",
                "口腔医学院研究生测试通知",
                datetime.date(2026, 7, 12),
            ),
            "ghi/tzgg": (
                "<div class='list-con clearfix'><ul><li><span class='date'>2024-05-31</span>"
                "<a href='../info/1018/1971.htm' title='全球健康研究院测试通知'>通知</a>"
                "</li></ul></div>",
                "全球健康研究院测试通知",
                datetime.date(2024, 5, 31),
            ),
        }
        for source_id, (html, title, date) in samples.items():
            with self.subTest(source_id=source_id):
                source = source_registry.require(source_id)
                result = extract_html_notifications(html, source, source.url)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].title, title)
                self.assertEqual(result[0].date, date)


class DetailDateFallbackTest(unittest.TestCase):
    class Response:
        def __init__(self, url, html, status=200):
            self.url = url
            self.content = html.encode("utf-8")
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class Session:
        def __init__(self, responses):
            self.responses = responses
            self.requested = []

        def get(self, url, timeout):
            self.requested.append((url, timeout))
            return self.responses[url]

    def test_missing_year_is_resolved_from_configured_detail_page(self):
        source = source_registry.require("cssy/tzgg")
        list_html = (
            "<meta charset='utf-8'><div class='lis_fy'><ul>"
            "<li><span class='fy_time'>04-06</span><a href='/info/1020/4491.htm' title='崇实第一条测试通知'>通知</a></li>"
            "<li><span class='fy_time'>12-24</span><a href='/info/1020/4488.htm' title='崇实第二条测试通知'>通知</a></li>"
            "</ul></div>"
        )
        session = self.Session({
            source.url: self.Response(source.url, list_html),
            "https://cssy.xjtu.edu.cn/info/1020/4491.htm": self.Response(
                "https://cssy.xjtu.edu.cn/info/1020/4491.htm",
                "<div class='nr_time'>日期：2022-04-06</div>",
            ),
            "https://cssy.xjtu.edu.cn/info/1020/4488.htm": self.Response(
                "https://cssy.xjtu.edu.cn/info/1020/4488.htm",
                "<div class='nr_time'>日期：2021-12-24</div>",
            ),
        })
        with patch.object(GenericListCrawler, "_session", return_value=session):
            crawler = GenericListCrawler("cssy/tzgg")
            result = crawler.get_notifications()

        self.assertEqual([one.date for one in result], [
            datetime.date(2022, 4, 6),
            datetime.date(2021, 12, 24),
        ])
        self.assertEqual(len(session.requested), 3)
        self.assertEqual(crawler.detail_errors, {})

    def test_detail_failures_are_isolated_and_never_guess_year(self):
        source = source_registry.require("cssy/tzgg")
        list_html = (
            "<div class='lis_fy'><ul>"
            "<li><span class='fy_time'>04-06</span><a href='/ok.htm' title='可正常解析的崇实通知'>通知</a></li>"
            "<li><span class='fy_time'>01-26</span><a href='/broken.htm' title='详情页异常的崇实通知'>通知</a></li>"
            "</ul></div>"
        )
        session = self.Session({
            source.url: self.Response(source.url, list_html),
            "https://cssy.xjtu.edu.cn/ok.htm": self.Response(
                "https://cssy.xjtu.edu.cn/ok.htm", "<div class='nr_time'>2022-04-06</div>"
            ),
            "https://cssy.xjtu.edu.cn/broken.htm": self.Response(
                "https://cssy.xjtu.edu.cn/broken.htm", "<div class='nr_time'>日期未知</div>"
            ),
        })
        with patch.object(GenericListCrawler, "_session", return_value=session):
            crawler = GenericListCrawler("cssy/tzgg")
            result = crawler.get_notifications()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].date, datetime.date(2022, 4, 6))
        self.assertNotEqual(result[0].date.year, datetime.date.today().year)
        self.assertIn("https://cssy.xjtu.edu.cn/broken.htm", crawler.detail_errors)

    def test_detail_retry_recovers_transient_failure(self):
        source = source_registry.require("cssy/tzgg")
        list_html = (
            "<div class='lis_fy'><ul><li><span class='fy_time'>04-06</span>"
            "<a href='/retry.htm' title='重试后成功的崇实通知'>通知</a></li></ul></div>"
        )

        class RetrySession:
            def __init__(self):
                self.requested = []
                self.detail_attempts = 0

            def get(inner_self, url, timeout):
                inner_self.requested.append((url, timeout))
                if url == source.url:
                    return self.Response(url, list_html)
                inner_self.detail_attempts += 1
                if inner_self.detail_attempts == 1:
                    raise RuntimeError("transient connection reset")
                return self.Response(url, "<div class='nr_time'>2022-04-06</div>")

        session = RetrySession()
        with patch.object(GenericListCrawler, "_session", return_value=session):
            crawler = GenericListCrawler("cssy/tzgg")
            result = crawler.get_notifications()

        self.assertEqual([one.date for one in result], [datetime.date(2022, 4, 6)])
        self.assertEqual(session.detail_attempts, 2)
        self.assertEqual(crawler.detail_errors, {})

    def test_detail_origin_and_request_limit_block_unbounded_fetches(self):
        source = source_registry.require("cssy/tzgg")
        limited_source = replace(
            source,
            selectors={**source.selectors, "detail_date_max": 1, "detail_date_retries": 0},
        )
        list_html = (
            "<meta charset='utf-8'><div class='lis_fy'><ul>"
            "<li><span class='fy_time'>04-06</span><a href='/one.htm' title='第一条限额通知'>通知</a></li>"
            "<li><span class='fy_time'>04-05</span><a href='/two.htm' title='第二条限额通知'>通知</a></li>"
            "<li><span class='fy_time'>04-04</span><a href='https://outside.example/three.htm' "
            "title='跨站链接不应请求'>通知</a></li>"
            "</ul></div>"
        )
        session = self.Session({
            source.url: self.Response(source.url, list_html),
            "https://cssy.xjtu.edu.cn/one.htm": self.Response(
                "https://cssy.xjtu.edu.cn/one.htm", "<div class='nr_time'>2022-04-06</div>"
            ),
        })
        with patch.object(GenericListCrawler, "_session", return_value=session):
            crawler = GenericListCrawler("cssy/tzgg")
            crawler.source = limited_source
            result = crawler.get_notifications()

        self.assertEqual([one.title for one in result], ["第一条限额通知"])
        self.assertEqual(len(session.requested), 2)
        self.assertIn("https://cssy.xjtu.edu.cn/two.htm", crawler.detail_errors)
        self.assertIn("https://outside.example/three.htm", crawler.detail_errors)


class MigrationTest(unittest.TestCase):
    def test_v1_config_expands_graduate_channels_and_preserves_unknown(self):
        old_rule = Ruleset(TagIncludeFilter("培养工作"), name="培养", enable=True).dump()
        manager = NotificationManager.load_or_create({
            "subscription": ["教务处", "研究生院", "future/source"],
            "ruleset": {"研究生院": [old_rule], "future/source": []},
        })
        self.assertEqual(manager.subscription[0], "dean/jxtz")
        self.assertTrue(all(f"gs/{channel}" in manager.subscription for channel in ("zsgz", "pygz", "gjjl", "xwgz", "yggz", "zhgz")))
        self.assertIn("future/source", manager.subscription)
        self.assertIn("future/source", manager.ruleset)
        self.assertIn("gs/pygz", manager.ruleset)
        self.assertEqual(manager.dump_config()["version"], 2)

    def test_v1_notification_keeps_read_state(self):
        notification = Notification.load({
            "title": "测试通知",
            "link": "https://example.test/item",
            "source": "研究生院",
            "description": "",
            "tags": ["培养工作"],
            "date": "2026-08-01",
            "is_read": True,
        })
        self.assertEqual(notification.source, "gs/pygz")
        self.assertTrue(notification.is_read)
        self.assertEqual(notification.dump()["source"], "gs/pygz")

    def test_v133_fixture_migrates_without_data_loss(self):
        fixture_dir = Path(__file__).with_name("fixtures")
        config = json.loads((fixture_dir / "notification_config_v1.json").read_text(encoding="utf-8"))
        cache = json.loads((fixture_dir / "notification_cache_v1.json").read_text(encoding="utf-8"))

        manager = NotificationManager.load_or_create(config)
        notifications = NotificationManager.load_notifications(cache)

        self.assertEqual(len(notifications), 2)
        self.assertTrue(notifications[0].is_read)
        self.assertFalse(notifications[1].is_read)
        self.assertIn("已下线的未来来源", manager.subscription)
        self.assertEqual(manager.ruleset["dean/jxtz"][0].name, "考试通知")
        self.assertEqual(manager.ruleset["gs/pygz"][0].name, "培养工作")


class FailureIsolationTest(unittest.TestCase):
    def test_one_source_failure_does_not_discard_other_source(self):
        good = Notification("可用通知", "https://example.test/good", "dean/jxtz")

        class StubCrawler:
            def __init__(self, source_id):
                self.source_id = source_id

            def get_notifications(self):
                if self.source_id == "gs/pygz":
                    raise RuntimeError("temporary failure")
                return [good]

        with patch(
            "notification.notification_manager.create_crawler",
            side_effect=lambda source_id, pages: StubCrawler(source_id),
        ):
            manager = NotificationManager(["dean/jxtz", "gs/pygz"])
            result = manager.get_notifications()

        self.assertEqual(result, [good])
        self.assertIn("gs/pygz", manager.last_errors)
        self.assertNotIn("dean/jxtz", manager.last_errors)


class ChallengeCacheTest(unittest.TestCase):
    def test_concurrent_client_id_updates_serialize_cache_writes(self):
        cache = {}
        state_lock = threading.Lock()
        active_writers = 0
        max_active_writers = 0

        def observe_write(_):
            nonlocal active_writers, max_active_writers
            with state_lock:
                active_writers += 1
                max_active_writers = max(max_active_writers, active_writers)
            time.sleep(0.002)
            with state_lock:
                active_writers -= 1

        with patch.object(crawler_module, "write_client_id", side_effect=observe_write):
            workers = [
                threading.Thread(
                    target=crawler_module.set_client_id,
                    args=(f"https://site-{index}.xjtu.edu.cn/", f"id-{index}", cache),
                )
                for index in range(12)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()

        self.assertEqual(len(cache), 12)
        self.assertEqual(max_active_writers, 1)


class RegistryTest(unittest.TestCase):
    def test_grouping_defaults_and_packaging(self):
        self.assertEqual(source_registry.defaults(), ("dean/jxtz",))
        self.assertEqual(len(source_registry.sources()), 78)
        self.assertEqual(
            Counter(source.status for source in source_registry.sources()),
            Counter({"verified": 78}),
        )
        roots = {source.root_group for source in source_registry.sources()}
        categories = {source.category for source in source_registry.sources()}
        self.assertEqual(roots, {"西安交通大学"})
        self.assertTrue({"校级部门", "学院与学部", "书院", "医学教育"}.issubset(categories))
        self.assertTrue(source_registry.require("cssy/tzgg").verified)
        self.assertTrue(source_registry.require("gjcnpt/jxyx").verified)
        self.assertTrue(source_registry.require("med/tzgg").verified)
        self.assertEqual(source_registry.require("med/tzgg").url, "http://www.med.xjtu.edu.cn/tzgg.htm")
        college_sources = [one for one in source_registry.sources() if one.category == "学院与学部"]
        self.assertTrue(college_sources)
        self.assertTrue(all(one.discipline in {"工学", "理学", "人文经管"} for one in college_sources))
        self.assertEqual({one.discipline for one in college_sources}, {"工学", "理学", "人文经管"})
        for source_id in (
            "sce/tzgg", "jsdi/xygg", "cy/tzgg", "sph/tzgg",
            "xjtu2h/bksjy", "xjtu2h/yjsjy", "dental/tzgg",
            "dental/bkjy", "dental/yjsjy", "ghi/tzgg",
        ):
            self.assertTrue(source_registry.require(source_id).verified)
        self.assertTrue(source_registry.require("innovation/jssc").verified)
        self.assertEqual(source_registry.require("xjtu2h/bksjy").level, "undergrad")
        self.assertEqual(source_registry.require("xjtu2h/yjsjy").level, "grad")
        self.assertEqual(source_registry.require("dental/bkjy").level, "undergrad")
        self.assertEqual(source_registry.require("dental/yjsjy").level, "grad")
        self.assertEqual(source_registry.require("sicmi/tzgg").site_name, "国家医学攻关平台（中心）")
        bjb = source_registry.require("bjb/tzgg")
        self.assertEqual(
            {(one.name, one.category, one.discipline) for one in bjb.directory_placements},
            {
                ("钱学森学院", "学院与学部", "工学"),
                ("钱学森书院", "书院", ""),
            },
        )
        academy_entries = {
            (source.site_id, placement.name)
            for source in source_registry.sources()
            for placement in source.directory_placements
            if placement.category == "书院"
        }
        self.assertEqual(len(academy_entries), 9)
        self.assertTrue(all(source.checked_on for source in source_registry.sources()))

        build_script = Path("build.py").read_text(encoding="utf-8")
        self.assertIn("notification/sources.json", build_script)

    def test_generic_crawler_has_no_site_specific_branches(self):
        generic_source = Path("notification/crawlers/generic.py").read_text(encoding="utf-8")
        for forbidden in ("cssy", "gjcnpt", "www.med.xjtu.edu.cn", "med/tzgg"):
            self.assertNotIn(forbidden, generic_source)

    def test_invalid_declarative_configs_fail_early_with_clear_errors(self):
        def registry_data(**channel_overrides):
            channel = {
                "id": "tzgg",
                "name": "通知公告",
                "url": "https://example.xjtu.edu.cn/tzgg.htm",
                "checked_on": "2026-08-04",
                **channel_overrides,
            }
            return {
                "version": 1,
                "sites": [{
                    "id": "example",
                    "name": "示例学院",
                    "root_group": "西安交通大学",
                    "category": "学院与学部",
                    "discipline": "工学",
                    "home": "https://example.xjtu.edu.cn/",
                    "channels": [channel],
                }],
            }

        cases = [
            ([], "must be an object"),
            (registry_data(url="https://user:secret@example.test/list.htm"), "Invalid URL"),
            (registry_data(selectors=[]), "must be an object"),
            (registry_data(selectors={"typo_xpath": "//li"}), "Unknown selector"),
            (registry_data(selectors={"item_xpath": "//*["}), "Invalid XPath"),
            (registry_data(selectors={"detail_date_max": 20}), "require detail_date_xpath"),
            (registry_data(selectors={"detail_date_xpath": "//time", "detail_date_max": 101}), "between 1 and 100"),
            (registry_data(checked_on="not-a-date"), "Invalid checked_on"),
        ]
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    SourceRegistry(payload)

        bad_discipline = registry_data()
        bad_discipline["sites"][0]["discipline"] = "交叉与其他"
        with self.assertRaisesRegex(ValueError, "college discipline"):
            SourceRegistry(bad_discipline)

        bad_crawler = registry_data(crawler="site-specific-python")
        with self.assertRaisesRegex(ValueError, "crawler type"):
            SourceRegistry(bad_crawler)

    def test_invalid_directory_placements_fail_early(self):
        def registry_with(placements):
            return {
                "version": 1,
                "sites": [{
                    "id": "example",
                    "name": "示例学院",
                    "root_group": "西安交通大学",
                    "category": "学院与学部",
                    "discipline": "工学",
                    "placements": placements,
                    "channels": [{
                        "id": "tzgg",
                        "name": "通知公告",
                        "url": "https://example.xjtu.edu.cn/tzgg.htm",
                        "checked_on": "2026-08-04",
                    }],
                }],
            }

        cases = [
            ({}, "must be a list"),
            (["书院"], "must be an object"),
            ([{"name": "别名", "category": "书院", "unknown": True}], "Unknown placement"),
            ([{"name": "示例学院", "category": "学院与学部", "discipline": "工学"}], "Duplicate placement"),
            ([{"name": "别名学院", "category": "学院与学部", "discipline": "其他"}], "college placement discipline"),
            ([{"name": "别名书院", "category": "书院", "discipline": "工学"}], "cannot have a discipline"),
            ([{"name": f"别名 {index}", "category": "书院"} for index in range(9)], "Too many placements"),
        ]
        for placements, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    SourceRegistry(registry_with(placements))


if __name__ == "__main__":
    unittest.main()
