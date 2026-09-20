import os
import tempfile
import unittest

from schedule.schedule_database import Exam, Term
from schedule.schedule_service import ScheduleService

TEST_DOMAIN = "schedule"
TEST_REGRESSION = True

TERM = "2025-2026-1"
TERM_START = "2025-09-08"
OTHER_TERM = "2026-2027-1"


def _exam_json(term_number: str = TERM, time_range: str = "08:00-10:00", name: str = "高等数学") -> dict:
    """构造一份 jwxt 兼容的考试 json（2026-01-05 是 TERM 的第 18 周，星期一）"""
    return {
        "term_number": term_number,
        "exams": [{
            "KCM": name,
            "KSSJMS": f"2026-01-05 {time_range}(星期一)",
            "JASMC": "主楼A-101",
            "ZWH": "12",
        }],
    }


class AddExamFromJsonTest(unittest.TestCase):
    """
    考试导入需要按学期开始日期换算到课表周次。该学期没有开始日期时既不能崩溃，
    也不能把已经导入的考试删掉。
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = ScheduleService(os.path.join(self.directory.name, "schedule.db"))

    def tearDown(self):
        # Windows 下不关闭连接会导致临时目录无法删除
        self.service.database.close()

    def test_imports_exam_and_computes_week_from_term_start(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)

        self.assertEqual(self.service.addExamFromJson(_exam_json()), 0)

        exam = Exam.select().get()
        self.assertEqual(exam.name, "高等数学考试")
        self.assertEqual(exam.term_number, TERM)
        self.assertEqual(exam.week_number, 18)
        self.assertEqual(exam.day_of_week, 1)
        self.assertEqual(exam.start_time, 1)
        self.assertEqual(exam.location, "主楼A-101")
        self.assertEqual(exam.seat_number, "12")

    def test_skips_without_deleting_existing_exam_when_term_start_unknown(self):
        """回归：缺少学期开始日期时曾抛 TypeError，且同名考试在崩溃前已被删除。"""
        self.service.setTermInfo(TERM, TERM_START, current=True)
        self.service.addExamFromJson(_exam_json())
        self.assertEqual(Exam.select().count(), 1)

        # 切换到没有 Term 记录的学期，再导入该学期的同一门课考试
        self.service.setCurrentTerm(OTHER_TERM)
        self.assertIsNone(self.service.getStartOfTerm())

        skipped = self.service.addExamFromJson(_exam_json(term_number=OTHER_TERM))
        self.assertEqual(skipped, 1)
        # 已导入的考试必须原样保留，而不是先被删除再崩溃
        self.assertEqual(Exam.select().count(), 1)
        exam = Exam.select().get()
        self.assertEqual(exam.term_number, TERM)
        self.assertEqual(exam.week_number, 18)

    def test_uses_exam_term_start_instead_of_current_term(self):
        """当前学期没有开始日期时，仍应按考试自己的学期换算周次。"""
        self.service.setTermInfo(TERM, TERM_START)
        self.service.setCurrentTerm(OTHER_TERM)
        self.assertIsNone(self.service.getStartOfTerm())

        self.assertEqual(self.service.addExamFromJson(_exam_json()), 0)
        self.assertEqual(Exam.select().get().week_number, 18)

    def test_unknown_term_reports_every_exam_as_skipped(self):
        payload = _exam_json(term_number=OTHER_TERM)
        payload["exams"] = payload["exams"] * 3

        self.assertEqual(self.service.addExamFromJson(payload), 3)
        self.assertEqual(Exam.select().count(), 0)

    def test_em_dash_time_range_is_still_parsed(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)

        self.assertEqual(self.service.addExamFromJson(_exam_json(time_range="08:00—10:00")), 0)
        self.assertEqual(Exam.select().count(), 1)

    def test_set_term_info_creates_term_row(self):
        """按考试自己的学期取开始日期，依赖 Term 表里确实写入了该学期。"""
        self.service.setTermInfo(TERM, TERM_START)

        self.assertEqual(Term.get(Term.term_number == TERM).start_date, TERM_START)


if __name__ == '__main__':
    unittest.main()
