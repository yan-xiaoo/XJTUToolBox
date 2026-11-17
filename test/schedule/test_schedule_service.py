import os
import tempfile
import unittest
from unittest.mock import patch

from schedule.schedule_database import Course, Exam, Term
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

    def test_fullwidth_colon_and_single_digit_hour(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        for text in ("9：00-11：00", "９：００－１１：００", "9:00 — 11:00"):
            with self.subTest(text=text):
                payload = _exam_json(time_range=text)
                payload["exams"][0]["KSSJMS"] = f"2026-01-08  {text}（星期四）"
                self.assertEqual(self.service.addExamFromJson(payload), 0)
                exam = Exam.select().get()
                self.assertEqual(exam.start_exact_time.isoformat(), "09:00:00")
                self.assertEqual(exam.end_exact_time.isoformat(), "11:00:00")
                self.assertEqual(exam.day_of_week, 4)

    def test_invalid_later_row_keeps_saved_exams(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        self.service.addExamFromJson(_exam_json())
        payload = _exam_json(time_range="09:00-11:00")
        payload["exams"].append({"KCM": "示例课程乙", "KSSJMS": "待定"})
        with self.assertRaises(ValueError):
            self.service.addExamFromJson(payload)
        self.assertEqual(Exam.select().get().start_exact_time.isoformat(), "08:00:00")

    def test_reimport_does_not_remove_same_course_in_other_term(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        self.service.setTermInfo(OTHER_TERM, "2026-09-07")
        self.service.addExamFromJson(_exam_json())
        other = _exam_json(term_number=OTHER_TERM)
        other["exams"][0]["KSSJMS"] = "2027-01-04 09:00-11:00"
        self.service.addExamFromJson(other)
        self.service.addExamFromJson(_exam_json())
        self.assertEqual(Exam.select().count(), 2)

    def test_invalid_later_row_does_not_leave_new_courses(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        payload = _exam_json(name="new course")
        payload["exams"].append({"KCM": "bad row", "KSSJMS": "pending"})
        with self.assertRaises(ValueError):
            self.service.addExamFromJson(payload)
        self.assertEqual(Course.select().count(), 0)
        self.assertEqual(Exam.select().count(), 0)

    def test_insert_failure_rolls_back_courses_and_existing_exams(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        self.service.addExamFromJson(_exam_json())
        existing_id = Exam.select().get().id
        payload = _exam_json(time_range="09:00-11:00")
        payload["exams"].extend(_exam_json(name="new course")["exams"])
        with patch.object(Exam, "bulk_create", side_effect=RuntimeError("synthetic insert failure")):
            with self.assertRaises(RuntimeError):
                self.service.addExamFromJson(payload)
        self.assertEqual(Course.select().count(), 1)
        self.assertEqual(Exam.select().get().id, existing_id)
        self.assertEqual(Exam.select().get().start_exact_time.isoformat(), "08:00:00")

    def test_same_course_multiple_exams_in_one_payload_are_preserved(self):
        self.service.setTermInfo(TERM, TERM_START, current=True)
        payload = _exam_json()
        payload["exams"].extend(_exam_json(time_range="14:00-16:00")["exams"])
        self.service.addExamFromJson(payload)
        self.service.addExamFromJson(payload)
        self.assertEqual(Exam.select().count(), 2)
        self.assertEqual(Course.select().count(), 1)


if __name__ == '__main__':
    unittest.main()
