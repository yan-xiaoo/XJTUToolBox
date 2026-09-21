import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from jwxt.calendar import CALENDAR_PAGE_URL, CalendarImage, SchoolCalendar

TEST_DOMAIN = "schedule"

# 教务处页面的真实结构：正文是一串 <a href="图片"><img ...></a>
_PAGE_HTML = """
<div id="vsb_content"><div><body>
<p><a href="../2025-2026-new.png" target="_blank"></a></p>
<p><a href="../2026-2027.jpg" target="_blank">
    <img src="/__local/8/E0/8B/example.jpg" class="img_vsb_content"></a></p>
<p><a href="../2025-2026-new.png" target="_blank">
    <img src="/__local/D/27/0D/example.png" class="img_vsb_content"></a></p>
<p><a href="../upload.png" target="_blank">
    <img src="/__local/B/4B/F4/example.jpg" alt="13180"></a></p>
<p><a href="http://jwc.xjtu.edu.cn/__local/6/B2/5C/abc_4E08F.jpg" target="_blank">&nbsp;
    <img src="/__local/6/B2/5C/abc_4E08F.jpg"></a></p>
<p><a title="2015-2016学年校历" href="/__local/F/59/FF/def_57EF5.jpg?e=.jpg" target="_blank">
    <img src="/__local/F/59/FF/def_57EF5.jpg?e=.jpg"></a></p>
<p><a href="../2026-2027.jpg" target="_blank">
    <img src="/__local/8/E0/8B/example.jpg"></a></p>
</body></div></div>
"""


def _session_with(html: str, status: int = 200) -> SimpleNamespace:
    response = SimpleNamespace(
        text=html,
        status_code=status,
        raise_for_status=Mock(
            side_effect=None if status < 400
            else requests.HTTPError(f"{status} error")
        ),
    )
    return SimpleNamespace(get=Mock(return_value=response))


class SchoolCalendarImageTest(unittest.TestCase):
    def test_parses_year_from_file_name_and_title_then_infers_the_rest(self):
        images = SchoolCalendar.parse_calendar_images(_PAGE_HTML)

        # 文件名给出 2026-2027、2025-2026，title 给出 2015-2016，中间两张按页面顺序推定
        self.assertEqual(
            [image.year for image in images],
            ["2026-2027", "2025-2026", "2024-2025", "2023-2024", "2015-2016"],
        )
        self.assertEqual(
            [image.label for image in images],
            ["2026-2027 学年", "2025-2026 学年", "2024-2025 学年", "2023-2024 学年", "2015-2016 学年"],
        )

    def test_urls_are_absolute_and_upgraded_to_https(self):
        images = SchoolCalendar.parse_calendar_images(_PAGE_HTML)

        self.assertEqual(images[0].url, "https://dean.xjtu.edu.cn/2026-2027.jpg")
        # 老校历的 title 提供学年，href 指向 __local
        self.assertEqual(
            images[-1].url,
            "https://dean.xjtu.edu.cn/__local/F/59/FF/def_57EF5.jpg?e=.jpg",
        )
        self.assertTrue(all(image.url.startswith("https://") for image in images))
        # 页面里 http://jwc.xjtu.edu.cn 的旧链接被升级为 https
        self.assertIn("https://jwc.xjtu.edu.cn/__local/6/B2/5C/abc_4E08F.jpg",
                      [image.url for image in images])

    def test_skips_anchors_without_image_and_deduplicates_urls(self):
        images = SchoolCalendar.parse_calendar_images(_PAGE_HTML)

        # 没有内嵌 <img> 的空锚点被跳过
        self.assertEqual(len(images), 5)
        # 末尾重复的 2026-2027 链接只保留一次
        self.assertEqual([image.url for image in images].count("https://dean.xjtu.edu.cn/2026-2027.jpg"), 1)

    def test_page_without_calendar_images_returns_empty_list(self):
        self.assertEqual(SchoolCalendar.parse_calendar_images("<div>没有图片</div>"), [])

    def test_relative_url_is_resolved_against_the_page_url(self):
        html = '<a href="sub/x.png"><img src="x"></a>'
        self.assertEqual(
            SchoolCalendar.parse_calendar_images(html)[0].url,
            "https://dean.xjtu.edu.cn/xxfw/sub/x.png",
        )

    def test_leading_annotated_free_images_are_inferred_backwards(self):
        """最新的一届没有标注时，从后面第一个已知学年往前推。"""
        html = (
            '<a href="/x/a.jpg"><img src="x"></a>'
            '<a href="/x/b.jpg"><img src="x"></a>'
            '<a title="2024-2025学年校历" href="/x/c.jpg"><img src="x"></a>'
        )
        self.assertEqual(
            [image.year for image in SchoolCalendar.parse_calendar_images(html)],
            ["2026-2027", "2025-2026", "2024-2025"],
        )

    def test_inference_resyncs_on_a_later_known_year(self):
        html = (
            '<a href="/x/2026-2027.jpg"><img src="x"></a>'
            '<a href="/x/mid.png"><img src="x"></a>'
            '<a title="2023-2024学年校历" href="/x/late.jpg"><img src="x"></a>'
        )
        # 中间那张按 2026-2027 递减得 2025-2026；后面已知的 2023-2024 以它为准
        self.assertEqual(
            [image.year for image in SchoolCalendar.parse_calendar_images(html)],
            ["2026-2027", "2025-2026", "2023-2024"],
        )

    def test_inferred_years_are_strictly_decreasing(self):
        html = "".join(
            f'<a href="/x/{name}"><img src="x"></a>' for name in
            ["2026-2027.jpg", "cal-a.png", "cal-b.png", "cal-c.png", "2015-2016.jpg", "2014-2015.jpg"]
        )
        self.assertEqual(
            [image.year for image in SchoolCalendar.parse_calendar_images(html)],
            ["2026-2027", "2025-2026", "2024-2025", "2023-2024", "2015-2016", "2014-2015"],
        )

    def test_without_any_anchor_years_stay_unknown(self):
        html = '<a href="/__local/A/B/C/hash_12345.jpg"><img src="x"></a>'
        image = SchoolCalendar.parse_calendar_images(html)[0]

        self.assertIsNone(image.year)
        self.assertEqual(image.label, "未标注学年")

    def test_get_calendar_images_uses_page_url_and_returns_parsed_result(self):
        session = _session_with(_PAGE_HTML)
        images = SchoolCalendar(session).get_calendar_images()

        self.assertEqual(session.get.call_args[0][0], CALENDAR_PAGE_URL)
        self.assertEqual(len(images), 5)
        self.assertIsInstance(images[0], CalendarImage)

    def test_http_error_propagates(self):
        with self.assertRaises(requests.HTTPError):
            SchoolCalendar(_session_with("", status=500)).get_calendar_images()


if __name__ == '__main__':
    unittest.main()
