import unittest
from types import SimpleNamespace

from library.seats import Library


class LibraryBookingParseTest(unittest.TestCase):
    def setUp(self):
        self.library = Library(SimpleNamespace())

    def test_no_booking(self):
        html = "<div>暂无预约</div>"
        self.assertIsNone(self.library._parse_booking(html, "暂无预约"))

    def test_active_booking_and_actions(self):
        body = "北楼二层外文库（东） 座位 A101 预约状态：已预约"
        html = """
        <div>北楼二层外文库（东） A101 预约状态：已预约</div>
        <script>showConfirmModal('确认','cancel','88')</script>
        <script>showConfirmModal('确认','ruguan1','88')</script>
        """
        booking = self.library._parse_booking(html, body)
        self.assertIsNotNone(booking)
        self.assertEqual(booking.seat_id, "A101")
        self.assertEqual(booking.area, "北楼二层外文库（东）")
        self.assertEqual(booking.status_text, "已预约")
        self.assertIn("取消预约", booking.action_urls)
        self.assertIn("入馆签到", booking.action_urls)

    def test_canceled_booking_is_ignored(self):
        body = "A101 预约状态：已取消"
        html = "<div>A101 预约状态：已取消</div>"
        self.assertIsNone(self.library._parse_booking(html, body))

    def test_multiple_statuses_picks_active(self):
        body = "A101 预约状态：已取消 B202 预约状态：使用中"
        html = """
        <div>A101 预约状态：已取消</div>
        <div>B202 预约状态：使用中</div>
        <script>showConfirmModal('确认','leave','9')</script>
        """
        booking = self.library._parse_booking(html, body)
        self.assertIsNotNone(booking)
        self.assertEqual(booking.seat_id, "B202")
        self.assertEqual(booking.status_text, "使用中")
        self.assertIn("中途离开", booking.action_urls)

    def test_actions_from_button_onclick(self):
        body = "北楼二层外文库（东） A101 预约状态：已预约"
        html = """
        <div>北楼二层外文库（东） A101 预约状态：已预约</div>
        <button onclick="showConfirmModal('确认取消','cancel','77')">取消预约</button>
        <a href="#" onclick="showConfirmModal('确认','ruguan1','77')">入馆签到</a>
        """
        booking = self.library._parse_booking(html, body)
        self.assertIsNotNone(booking)
        self.assertIn("取消预约", booking.action_urls)
        self.assertIn("入馆签到", booking.action_urls)
        self.assertIn("ri=77", booking.action_urls["取消预约"])

    def test_actions_from_form_and_double_quotes(self):
        body = "北楼二层外文库（东） A101 预约状态：已预约"
        html = """
        <div>北楼二层外文库（东） A101 预约状态：已预约</div>
        <script>showConfirmModal("确认","cancel","66")</script>
        <form action="/my/?firstruguan=1&ri=66">
            <input type="submit" value="入馆签到">
        </form>
        """
        booking = self.library._parse_booking(html, body)
        self.assertIsNotNone(booking)
        self.assertIn("取消预约", booking.action_urls)
        self.assertIn("入馆签到", booking.action_urls)

    def test_invalid_json_has_stable_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.library._parse_json("{not json")
        self.assertIn("无法解析", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
