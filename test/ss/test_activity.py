import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from ss import Activity, ActivityStatus, ApplyMode, Order, SsActivity, SsError, activity_tags
from ss.activity import ActivityDetail, MyApply, _rows

TEST_DOMAIN = "auth-session"

ROW = {
    "HDDM": "A1", "HDMC": "高等数学学习方法讲座", "HDLX_DISPLAY": "学术科技", "SSBM_DISPLAY": "数学学院",
    "HDKSSJ": "2026-12-01 19:00", "HDJSSJ": "2026-12-01 21:00", "HDZT": "", "CYRS": "35", "HDZF": "2",
    "ZPURL": "/xsfw/cover.png",
}
DETAIL = {
    **ROW, "HDNR": "<p>本次为<span>集</span>体活动</p>", "HDXZ": "", "SFXYBM": "1", "BMFS": "1",
    "BMKSSJ": "2026-11-20 08:00", "BMJSSJ": "2026-11-30 18:00", "BMXZRS": "100", "BMSH": "0",
    "HASAPPLY": "0", "SFXCQD": "1", "LLF": "1", "BMF": "2", "QDF": "0",
}


def _response(payload, status=200):
    return SimpleNamespace(status_code=status, json=Mock(return_value=payload))


class SsActivityParseTest(unittest.TestCase):
    def test_rows_accepts_list_and_wrapped_shapes(self):
        self.assertEqual(_rows([ROW, "x"]), [ROW])
        self.assertEqual(_rows({"rows": [ROW]}), [ROW])
        self.assertEqual(_rows({"totalSize": 1, "list": [ROW]}), [ROW])
        self.assertEqual(_rows(None), [])

    def test_list_sends_emap_form_and_parses_rows(self):
        session = Mock()
        session.post.return_value = _response({"code": "0", "data": {"rows": [ROW]}})
        rows = SsActivity(session).list("讲座", Order.HOT)
        sent = json.loads(session.post.call_args.kwargs["data"]["data"])
        self.assertEqual(sent["orderColumns"], "-CYRS")
        self.assertEqual(json.loads(sent["querySetting"])[0][0]["value"], "讲座")
        a = rows[0]
        self.assertEqual((a.id, a.status, a.participants), ("A1", ActivityStatus.UPCOMING, 35))
        self.assertEqual(a.cover, "https://ss.xjtu.edu.cn/xsfw/cover.png")
        self.assertTrue(a.likely_group_proof)

    def test_nonzero_code_raises_message(self):
        session = Mock()
        session.post.return_value = _response({"code": "1", "msg": "报名已截止"})
        with self.assertRaisesRegex(SsError, "报名已截止"):
            SsActivity(session).apply("A1")

    def test_detail_fields_and_explicit_tag_across_html(self):
        d = ActivityDetail.from_row(DETAIL)
        self.assertEqual(d.apply_mode, ApplyMode.ONE_CLICK)
        self.assertEqual(d.quota, 100)
        self.assertEqual(d.points_breakdown, "浏览 1 · 报名 2")
        self.assertEqual(d.explicit_tags, ["集体活动"])

    def test_apply_blocker_checks_window_and_state(self):
        d = ActivityDetail.from_row(DETAIL)
        self.assertIsNone(d.apply_blocker(datetime(2026, 11, 25)))
        self.assertIn("还没开始", d.apply_blocker(datetime(2026, 11, 1)))
        self.assertIn("已截止", d.apply_blocker(datetime(2026, 12, 1)))
        self.assertEqual(ActivityDetail.from_row({**DETAIL, "HASAPPLY": "1"}).apply_blocker(datetime(2026, 11, 25)),
                         "已经报过名了")
        self.assertIn("网页", ActivityDetail.from_row({**DETAIL, "BMFS": "3"}).apply_blocker(datetime(2026, 11, 25)))

    def test_tags_prefer_explicit_over_guess(self):
        a = Activity.from_row({**ROW, "SFXYBM": "0", "KCXZ_DISPLAY": "选修"})
        self.assertEqual(activity_tags(a), [("疑似集体活动", False), ("无需报名", False), ("选修", False)])
        self.assertEqual(activity_tags(a, ["集体活动"], True), [("集体活动", True), ("选修", False)])
        self.assertIsNone(Activity.from_row(ROW).need_apply)

    def test_my_apply_numeric_status(self):
        self.assertEqual(MyApply.from_row({"HDDM": "A1", "HDZT": "2", "SHZT": "99"}).activity_status, "进行中")
        self.assertEqual(MyApply.from_row({"HDDM": "A1", "HDZT": "3"}).activity_status, "已结束")
        self.assertEqual(MyApply.from_row({"HDDM": "A1", "SHZT": "99"}).review, "已通过")


if __name__ == "__main__":
    unittest.main()
