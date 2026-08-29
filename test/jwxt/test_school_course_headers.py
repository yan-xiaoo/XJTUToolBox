import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jwxt.school_course import SchoolCourseQuery

TEST_DOMAIN = "schedule"


class SchoolCourseHeadersTest(unittest.TestCase):
    def test_departments_sends_kcbcx_referer(self):
        session = SimpleNamespace(
            get=Mock(),
            post=Mock(return_value=SimpleNamespace(json=lambda: {
                "datas": {"code": {"rows": [{"id": "1", "name": "物理学院"}]}},
            })),
        )
        departments = SchoolCourseQuery(session).departments()
        self.assertEqual(departments, [("1", "物理学院")])
        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Referer"], SchoolCourseQuery.INIT_URL)
        self.assertIn("application/x-www-form-urlencoded", headers["Content-Type"])

    def test_query_setting_does_not_embed_order(self):
        session = SimpleNamespace(
            get=Mock(),
            post=Mock(return_value=SimpleNamespace(json=lambda: {
                "datas": {"qxfbkccx": {"totalSize": 0, "rows": []}},
            })),
        )
        SchoolCourseQuery(session).query(term="2025-2026-2")
        data = session.post.call_args.kwargs["data"]
        conditions = json.loads(data["querySetting"])
        self.assertTrue(all(not (isinstance(item, dict) and item.get("name") == "*order") for item in conditions))
        self.assertEqual(data["*order"], "+KKDWDM,+KCH,+KXH")


if __name__ == "__main__":
    unittest.main()
