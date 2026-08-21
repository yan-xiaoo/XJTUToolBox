import unittest
from types import SimpleNamespace
from unittest.mock import patch

from library.seats import ACTION_LABELS, BASE_URL, Library, MyBooking


def make_response(text: str, url: str = "http://rg.lib.xjtu.edu.cn:8086/seat/"):
    """构造一个最小可用的 requests.Response 替身。"""
    return SimpleNamespace(text=text, url=url, headers={})


class LibraryBookingTest(unittest.TestCase):
    def setUp(self):
        self.library = Library(SimpleNamespace())

    # ---- 动作映射表（与前端源码一致）----

    def test_action_labels_match_frontend_switch(self):
        """前端 onClick 的 switch(currentAction) 与动作名一一对应。"""
        self.assertEqual(ACTION_LABELS, {
            "cancel": "取消预约",
            "ruguan1": "入馆签到",
            "leave": "中途离开",
            "return": "中途返回",
        })

    # ---- 预约页解析 ----

    def test_no_booking(self):
        html = "<div>暂无预约</div>"
        self.assertIsNone(self.library._booking_from_html(html))

    def test_no_booking_with_plain_three_digit_numbers(self):
        """“暂无预约”页面里的统计数字不得被误判为预约。"""
        self.assertIsNone(self.library._booking_from_html("<div>今日累计 120 人次，暂无预约</div>"))

    def test_booking_parse_rejects_plain_number_seat(self):
        """纯数字不算座位号（无字母前缀）。"""
        self.assertIsNone(self.library._booking_from_html("<div>120 预约状态：已预约</div>"))

    def test_active_booking_and_actions(self):
        html = """
        <div>北楼二层外文库（东） A101 预约状态：已预约</div>
        <script>showConfirmModal('确认', 'cancel', '88')</script>
        <script>showConfirmModal('确认', 'ruguan1', '88')</script>
        """
        booking = self.library._booking_from_html(html)
        self.assertIsNotNone(booking)
        self.assertEqual(booking.seat_id, "A101")
        self.assertEqual(booking.area, "北楼二层外文库（东）")
        self.assertEqual(booking.status_text, "已预约")
        self.assertEqual(booking.action_urls, {
            "取消预约": f"{BASE_URL}/my/?cancel=1&ri=88",
            "入馆签到": f"{BASE_URL}/my/?firstruguan=1&ri=88",
        })

    def test_webvpn_entity_quoted_actions(self):
        """WebVPN 把引号实体化并包裹在 vpn_rewrite_js(eval) 中，动作仍应可解析。

        依据真实页面结构：onclick="...eval(vpn_rewrite_js((function () {
        showConfirmModal(&#39;确认您已到馆?&#39;, &#39;ruguan1&#39;, &#39;4953117&#39;); })...
        """
        html = """
        <div>北楼二层外文库（东） D004 预约状态：待入馆</div>
        <a href="#" onclick="var vpn_return;eval(vpn_rewrite_js((function () { showConfirmModal(&#39;确认取消申请?注意：取消申请后三十分钟内不可提交线上预约&#39;, &#39;cancel&#39;, &#39;4953117&#39;); }).toString().slice(14, -2), 2));return vpn_return;">取消预约</a>
        <a href="#" onclick="var vpn_return;eval(vpn_rewrite_js((function () { showConfirmModal(&#39;确认您已到馆?&#39;, &#39;ruguan1&#39;, &#39;4953117&#39;); }).toString().slice(14, -2), 2));return vpn_return;">线上签到</a>
        """
        booking = self.library._booking_from_html(html, "https://webvpn.xjtu.edu.cn/.../my/")
        self.assertIsNotNone(booking)
        self.assertEqual(booking.seat_id, "D004")
        self.assertEqual(booking.action_urls, {
            "取消预约": f"{BASE_URL}/my/?cancel=1&ri=4953117",
            "入馆签到": f"{BASE_URL}/my/?firstruguan=1&ri=4953117",
        })

    def test_actions_only_include_present_buttons(self):
        """未入馆的预约只渲染取消/签到，不应出现离开/返回按钮。"""
        html = """
        <div>北楼二层外文库（东） D004 预约状态：待入馆</div>
        <script>showConfirmModal('确认取消申请?', 'cancel', '77')</script>
        <script>showConfirmModal('确认您已到馆?', 'ruguan1', '77')</script>
        """
        booking = self.library._booking_from_html(html)
        self.assertEqual(set(booking.action_urls), {"取消预约", "入馆签到"})
        self.assertNotIn("中途离开", booking.action_urls)
        self.assertNotIn("中途返回", booking.action_urls)

    def test_reserve_id_from_url_fallback(self):
        """页面无 JS 动作调用时，从地址中的 ri 参数提取。"""
        self.assertEqual(self.library._reserve_id_and_actions("", f"{BASE_URL}/my/?cancel=1&ri=42")[0], "42")

    def test_reserve_id_empty_without_actions(self):
        self.assertEqual(self.library._reserve_id_and_actions("<div>无预约</div>", f"{BASE_URL}/my/")[0], "")

    def test_build_actions_empty_without_reserve_id(self):
        self.assertEqual(self.library._build_actions("", {"取消预约"}), {})

    # ---- JSON 解析 ----

    def test_parse_json_success(self):
        self.assertEqual(self.library._parse_json('{"seat": {"A1": 0}}'), {"seat": {"A1": 0}})

    def test_parse_json_non_json_body(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.library._parse_json("<html>页面</html>")
        self.assertIn("非 JSON", str(ctx.exception))

    def test_invalid_json_has_stable_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.library._parse_json("{not json")
        self.assertIn("无法解析", str(ctx.exception))

    # ---- 查空座 ----

    def test_get_seats_parses_json(self):
        payload = '{"seat": {"A101": 0, "A102": 1}, "scount": {"north2east": [30, 12]}}'
        self.library.session.get = lambda *a, **k: make_response(payload)
        seats, stats = self.library.get_seats("north2east")
        self.assertEqual([(s.seat_id, s.available) for s in seats], [("A101", True), ("A102", False)])
        self.assertEqual(stats["north2east"].total, 30)
        self.assertEqual(stats["north2east"].available, 12)

    # ---- 换座：严格相等，禁止子串误判 ----

    def test_swap_seat_requires_exact_match(self):
        """回显座位号是目标座位号的子串时（如 A01 vs A011），不得判定换座成功。"""
        self.library.session.get = lambda *a, **k: make_response("")
        with patch.object(self.library, "get_my_booking", return_value=MyBooking("A011", "", "已预约", {})):
            result = self.library._swap_seat("A01", "north2east")
        self.assertFalse(result.success)
        self.assertIn("A011", result.message)

    def test_swap_seat_success_on_exact_match(self):
        self.library.session.get = lambda *a, **k: make_response("")
        with patch.object(self.library, "get_my_booking", return_value=MyBooking("A01", "", "已预约", {})):
            result = self.library._swap_seat("A01", "north2east")
        self.assertTrue(result.success)
        self.assertIn("已换座到 A01", result.message)

    # ---- 预约座位 ----

    def test_book_seat_success_lands_on_my_page(self):
        html = """
        <div>北楼二层外文库（东） A101 预约状态：已预约</div>
        <script>showConfirmModal('确认', 'cancel', '88')</script>
        """
        self.library.session.get = lambda *a, **k: make_response(html, f"{BASE_URL}/my/")
        result = self.library.book_seat("A101", "north2east")
        self.assertTrue(result.success)
        self.assertEqual(result.booking.seat_id, "A101")

    def test_book_seat_seat_taken(self):
        self.library.session.get = lambda *a, **k: make_response("<div>该座位已被预约</div>")
        result = self.library.book_seat("A101", "north2east")
        self.assertFalse(result.success)
        self.assertIn("已被他人预约", result.message)

    def test_book_seat_auto_swaps_when_already_booked(self):
        """已有预约时自动转换座；换座未生效则返回失败消息。"""
        def fake_get(url, *a, **k):
            if "seat/?" in url:
                return make_response("<div>已有预约，是否换座</div>")
            return make_response("")
        self.library.session.get = fake_get
        with patch.object(self.library, "get_my_booking", return_value=MyBooking("A999", "", "已预约", {})):
            result = self.library.book_seat("A101", "north2east")
        self.assertFalse(result.success)
        self.assertIn("A999", result.message)

    def test_get_my_booking_no_active_returns_none(self):
        self.library.session.get = lambda *a, **k: make_response("<div>暂无预约</div>", f"{BASE_URL}/my/")
        self.assertIsNone(self.library.get_my_booking())

    # ---- 失败原因 ----

    def test_failure_reason_mapping(self):
        cases = {
            "30分钟内不能重复预约": "30 分钟内不能重复预约",
            "该座位已被预约": "该座位已被他人预约",
            "您已有预约": "您已有其他座位预约",
            "当前不在预约时间": "当前不在预约开放时间",
            "系统维护中": "系统维护中",
            "未知错误": "预约失败",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.library._failure_reason(text), expected)


if __name__ == "__main__":
    unittest.main()