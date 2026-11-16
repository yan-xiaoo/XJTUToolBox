import json
from datetime import date, timedelta
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from icalendar import Calendar
from xjtu_calendar.exporter import build_ics_for_semester
from xjtu_calendar.subscribe import load_state

from schedule.calendar_service import CalendarService
from schedule.calendar_worker import execute
from schedule.schedule_database import Course, CourseInstance, Exam, set_config
from schedule.schedule_service import ScheduleService

TEST_DOMAIN = "schedule"
TEST_REGRESSION = True
TERM = "2099-2100-1"
START = date(2099, 9, 7)
START -= timedelta(days=START.weekday())


class CalendarServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.db = ScheduleService(str(self.directory / "schedule.db"))
        self.addCleanup(self.db.database.close)
        self.db.setTermInfo(TERM, START.isoformat(), current=True)
        self.db.addCourse("示例课程甲", 1, 5, 6, "示例教室", "示例教师", [1, 5])
        self.service = CalendarService(self.directory, TERM)

    def prepare(self, mode="subscription"):
        return self.service.prepare(self.service.snapshot(self.db), mode)

    def test_snapshot_uses_actual_summer_and_winter_dates(self):
        cfg = self.prepare()
        result = build_ics_for_semester(cfg, TERM)
        cal = Calendar.from_ical(result.ics)
        events = sorted(cal.walk("VEVENT"), key=lambda e: e.decoded("DTSTART"))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].decoded("DTSTART").strftime("%H:%M"), "14:30")
        self.assertEqual(events[1].decoded("DTSTART").strftime("%H:%M"), "14:00")
        self.assertTrue(cal.walk("VTIMEZONE"))
        self.assertTrue(all("UID" in e and "DTSTAMP" in e for e in events))

    def test_unchanged_snapshot_keeps_bytes_and_mtime(self):
        cfg = self.prepare()
        before = cfg.raw_timetable_path(TERM).stat().st_mtime_ns
        first = build_ics_for_semester(cfg, TERM).ics
        self.prepare()
        self.assertEqual(cfg.raw_timetable_path(TERM).stat().st_mtime_ns, before)
        self.assertEqual(build_ics_for_semester(cfg, TERM).ics, first)

    def test_uid_survives_display_edits_and_database_row_recreation(self):
        cfg = self.prepare()
        before = {str(e["UID"]) for e in Calendar.from_ical(build_ics_for_semester(cfg, TERM).ics).walk("VEVENT")}
        CourseInstance.update(name="修改显示名", location="另一间教室").execute()
        self.prepare()
        edited = {str(e["UID"]) for e in Calendar.from_ical(build_ics_for_semester(cfg, TERM).ics).walk("VEVENT")}
        self.assertEqual(edited, before)
        self.db.clearAllCourses()
        Course.delete().execute()
        self.db.addCourse("示例课程甲", 1, 5, 6, "示例教室", "示例教师", [1, 5])
        self.prepare()
        refreshed = {str(e["UID"]) for e in Calendar.from_ical(build_ics_for_semester(cfg, TERM).ics).walk("VEVENT")}
        self.assertEqual(refreshed, before)

    def test_account_namespaces_are_separate(self):
        first = self.service.snapshot(self.db)["courses"][0]["KCH"]
        directory = self.directory / "other-account"
        directory.mkdir()
        other_db = ScheduleService(str(directory / 'schedule.db'))
        self.addCleanup(other_db.database.close)
        other_db.setTermInfo(TERM, START.isoformat(), current=True)
        other_db.addCourse("示例课程甲", 1, 5, 6, "教室", "教师", [1])
        other = CalendarService(directory, TERM)
        self.assertNotEqual(other.snapshot(other_db)["courses"][0]["KCH"], first)
        with self.assertRaisesRegex(ValueError, "账户数据库已切换"):
            self.service.snapshot(self.db)
        with self.assertRaisesRegex(ValueError, "账户数据库已切换"):
            self.service.snapshot(other_db)

    def test_export_and_subscription_ledgers_are_separate(self):
        self.assertNotEqual(self.prepare("export").home, self.prepare("subscription").home)

    def test_empty_timetable_is_rejected_before_replacing_snapshot(self):
        cfg = self.prepare()
        previous = cfg.raw_timetable_path(TERM).read_bytes()
        self.db.clearAllCourses()
        with self.assertRaisesRegex(ValueError, "没有课程"):
            self.prepare()
        self.assertEqual(cfg.raw_timetable_path(TERM).read_bytes(), previous)

    def test_semester_cannot_escape_account_directory(self):
        for term in ("../other", "a/b", "..", "", "a\\b"):
            with self.subTest(term=term), self.assertRaises(ValueError):
                CalendarService(self.directory, term)

    def test_invalid_configuration_leaves_existing_files_unchanged(self):
        self.prepare()
        before = self.service.calendar_path.read_bytes()
        calendar = json.loads(before)
        calendar["semester"]["key"] = "another-term"
        with self.assertRaises(ValueError):
            self.service.save_configuration(calendar, {})
        self.assertEqual(self.service.calendar_path.read_bytes(), before)

    def test_makeup_uses_source_week_and_target_date_schedule(self):
        self.prepare()
        calendar = json.loads(self.service.calendar_path.read_text(encoding="utf-8"))
        target = START + timedelta(days=35)
        calendar["excluded_dates"] = [START.isoformat()]
        calendar["overrides"] = {target.isoformat(): {"source_date": START.isoformat()}}
        self.service.save_configuration(calendar, json.loads(self.service.schedule_path.read_text()))
        result = build_ics_for_semester(self.prepare(), TERM)
        days = {e.decoded("DTSTART").date() for e in Calendar.from_ical(result.ics).walk("VEVENT")}
        self.assertNotIn(START, days)
        self.assertIn(target, days)

    def test_export_preserves_alarm_and_crlf(self):
        self.db.addExamFromJson({"term_number": TERM, "exams": [
            {"KCM": "示例课程甲", "KSSJMS": f"{START} 9：00-11：00", "ZWH": None}]})
        cfg = self.prepare("export")
        output = self.directory / "calendar.ics"
        execute({"action": "export", "home": str(cfg.home), "term": TERM,
                 "output": str(output), "alarm": True})
        raw = output.read_bytes()
        self.assertNotIn(b"\r\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        events = Calendar.from_ical(raw).walk("VEVENT")
        self.assertEqual(len(events), 3)
        triggers = [e.walk("VALARM")[0].decoded("TRIGGER") for e in events]
        self.assertCountEqual(triggers, [timedelta(minutes=-15), timedelta(minutes=-15), timedelta(minutes=-30)])

    def test_export_cannot_overwrite_internal_state(self):
        cfg = self.prepare("export")
        with self.assertRaises(ValueError):
            execute({"action": "export", "home": str(cfg.home), "term": TERM,
                     "output": str(cfg.raw_timetable_path(TERM))})

    def exam_rows(self):
        return [{"KCM": "示例课程甲", "KSSJMS": f"{START + timedelta(days=d)} 9：00-11：00",
                 "JASMC": "原教室"} for d in (1, 2)]

    def export_request(self):
        cfg = self.prepare("export")
        return cfg, {"action": "export", "home": str(cfg.home), "term": TERM,
                     "output": str(self.directory / "exam-review.ics")}

    def test_partial_refresh_keeps_other_sittings_and_updates_known_sitting(self):
        rows = self.exam_rows()
        self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": rows})
        cfg, request = self.export_request()
        execute(request)
        rows[0]["JASMC"] = "新教室"
        self.db.addExamFromJson({"term_number": TERM, "complete": False, "exams": rows[:1]})
        self.assertEqual(Exam.select().count(), 2)
        self.assertEqual(Exam.select().where(Exam.location == "新教室").count(), 1)
        self.prepare("export")
        execute(request)
        events = Calendar.from_ical(Path(request["output"]).read_bytes()).walk("VEVENT")
        self.assertFalse(any(str(e.get("STATUS", "")) == "CANCELLED" for e in events))

    def test_incomplete_snapshot_cannot_retract_an_exam_in_export_push_or_rotate(self):
        self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": self.exam_rows()})
        cfg, request = self.export_request()
        execute(request)
        output = Path(request["output"])
        original = output.read_bytes()
        ledger = cfg.exam_ledger_path(TERM).read_bytes()
        cfg.subscribe_dir.mkdir(parents=True, exist_ok=True)
        (cfg.subscribe_dir / f"last-{TERM}.ics").write_bytes(original)
        Exam.delete().execute()
        set_config(f"calendar_exams_complete_{TERM}", "0")
        self.prepare("export")
        with patch("schedule.calendar_worker.cmd_subscribe") as subscribe:
            for action in ("export", "push", "rotate"):
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, "考试列表尚不完整"):
                    execute({**request, "action": action})
            subscribe.assert_not_called()
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(cfg.exam_ledger_path(TERM).read_bytes(), ledger)

    def test_complete_empty_snapshot_cancels_exams_and_partial_refresh_keeps_cancellations(self):
        self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": self.exam_rows()})
        cfg, request = self.export_request()
        execute(request)
        self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": []})
        self.prepare("export")
        execute(request)
        raw = Path(request["output"]).read_bytes()
        self.assertEqual(sum(str(e.get("STATUS", "")) == "CANCELLED"
                             for e in Calendar.from_ical(raw).walk("VEVENT")), 2)
        self.db.addExamFromJson({"term_number": TERM, "complete": False, "exams": []})
        self.prepare("export")
        execute(request)
        self.assertEqual(Path(request["output"]).read_bytes(), raw)

    def test_missing_or_corrupt_ledger_blocks_incomplete_export_then_recovers(self):
        for damaged in (None, 'broken ledger', 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'):
            with self.subTest(damaged=damaged):
                self.db.addExamFromJson({'term_number': TERM, 'complete': True, 'exams': self.exam_rows()})
                cfg, request = self.export_request()
                execute(request)
                original = Path(request['output']).read_bytes()
                Exam.delete().execute()
                set_config(f'calendar_exams_complete_{TERM}', '0')
                self.prepare('export')
                ledger = cfg.exam_ledger_path(TERM)
                if damaged is None:
                    ledger.unlink()
                else:
                    ledger.write_text(damaged, encoding='utf-8')
                with self.assertRaises(ValueError):
                    execute(request)
                self.assertEqual(Path(request['output']).read_bytes(), original)
                self.db.addExamFromJson({'term_number': TERM, 'complete': True, 'exams': self.exam_rows()})
                self.prepare('export')
                execute(request)
                self.assertEqual(len(Calendar.from_ical(Path(request['output']).read_bytes()).walk('VEVENT')), 4)

    def test_calendar_event_is_not_mistaken_for_missing_exam(self):
        from xjtu_calendar.calendar_events import make_calendar_uid
        from icalendar import Event
        cfg, request = self.export_request()
        execute(request)
        calendar = json.loads(cfg.semester_config_path(TERM).read_text(encoding='utf-8'))
        calendar['events'] = [{'source_id': 'semester-start'}]
        cfg.semester_config_path(TERM).write_text(json.dumps(calendar), encoding='utf-8')
        baseline = Calendar.from_ical(Path(request['output']).read_bytes())
        event = Event()
        event.add('uid', make_calendar_uid(TERM, 'semester-start'))
        event.add('dtstart', START)
        baseline.add_component(event)
        Path(request['output']).write_bytes(baseline.to_ical())
        from schedule.calendar_worker import require_safe_exam_snapshot
        require_safe_exam_snapshot(cfg, TERM, Path(request['output']))


class CalendarSubscriptionRehearsalTest(unittest.TestCase):
    """Exercise the real engine and git transport against a local bare repo."""
    setUp = CalendarServiceTest.setUp
    prepare = CalendarServiceTest.prepare

    def test_partial_exam_refresh_and_complete_cancellation_are_safe(self):
        remote = self.directory / "exam-remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)],
                       cwd=self.directory, check=True, capture_output=True)
        rows = CalendarServiceTest.exam_rows(self)
        self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": rows})
        cfg = self.prepare()
        base = {"home": str(cfg.home), "term": TERM}
        baseline = cfg.subscribe_dir / f"last-{TERM}.ics"
        def tip():
            return subprocess.check_output(["git", "--git-dir", str(remote), "rev-parse", "cal"],
                                           cwd=self.directory)
        with patch.dict("os.environ", {"GIT_AUTHOR_NAME": "Calendar Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                                       "GIT_COMMITTER_NAME": "Calendar Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}):
            execute({**base, "action": "init", "repo": remote.as_uri(),
                     "url_base": "https://calendar.example.invalid/", "branch": "cal"})
            execute({**base, "action": "push"})
            rows[0]["JASMC"] = "修改后的考场"
            self.db.addExamFromJson({"term_number": TERM, "complete": False, "exams": rows[:1]})
            self.prepare()
            execute({**base, "action": "push"})
            self.assertFalse(any(str(e.get("STATUS", "")) == "CANCELLED"
                                 for e in Calendar.from_ical(baseline.read_bytes()).walk("VEVENT")))
            previous_tip = tip()
            previous_baseline = baseline.read_bytes()
            Exam.delete().where(Exam.location == "原教室").execute()
            self.prepare()
            for action in ("push", "rotate"):
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, "考试列表尚不完整"):
                    execute({**base, "action": action})
            self.assertEqual(tip(), previous_tip)
            self.assertEqual(baseline.read_bytes(), previous_baseline)
            self.db.addExamFromJson({"term_number": TERM, "complete": True, "exams": rows[:1]})
            self.prepare()
            execute({**base, "action": "push"})
            self.assertEqual(sum(str(e.get("STATUS", "")) == "CANCELLED"
                                 for e in Calendar.from_ical(baseline.read_bytes()).walk("VEVENT")), 1)

    def test_publish_update_cancel_noop_repair_and_rotate(self):
        remote = self.directory / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)],
                       cwd=self.directory, check=True, capture_output=True)
        cfg = self.prepare()
        base = {"home": str(cfg.home), "term": TERM}
        with patch.dict("os.environ", {"GIT_AUTHOR_NAME": "Calendar Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                                       "GIT_COMMITTER_NAME": "Calendar Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}):
            execute({**base, "action": "init", "repo": remote.as_uri(),
                     "url_base": "https://calendar.example.invalid/", "branch": "cal"})
            execute({**base, "action": "push"})
            state = load_state(cfg, TERM)
            original_token = state.token
            baseline = cfg.subscribe_dir / f"last-{TERM}.ics"
            initial = baseline.read_bytes()
            original_events = Calendar.from_ical(initial).walk("VEVENT")
            original_uids = {str(e["UID"]) for e in original_events}

            def tip():
                return subprocess.check_output(["git", "--git-dir", str(remote), "rev-parse", "cal"],
                                               cwd=self.directory)

            first_tip = tip()
            self.prepare()
            execute({**base, "action": "push"})
            self.assertEqual(tip(), first_tip)

            CourseInstance.update(location="修改后的教室").execute()
            self.prepare()
            execute({**base, "action": "push"})
            updated = Calendar.from_ical(baseline.read_bytes()).walk("VEVENT")
            self.assertEqual({str(e["UID"]) for e in updated}, original_uids)
            self.assertTrue(all(int(e["SEQUENCE"]) == 1 for e in updated))

            CourseInstance.delete().where(CourseInstance.week_number == 5).execute()
            self.prepare()
            execute({**base, "action": "push"})
            cancelled = Calendar.from_ical(baseline.read_bytes()).walk("VEVENT")
            self.assertEqual(sum(str(e.get("STATUS", "")) == "CANCELLED" for e in cancelled), 1)
            cancelled_tip = tip()
            execute({**base, "action": "push"})
            self.assertEqual(tip(), cancelled_tip)

            # Repair uses the committed journal and the remote bytes.
            baseline.unlink()
            with self.assertRaisesRegex(ValueError, '发布留底缺失'):
                execute({**base, 'action': 'rotate'})
            self.assertEqual(load_state(cfg, TERM).token, original_token)
            self.assertEqual(tip(), cancelled_tip)
            execute({**base, "action": "repair"})
            self.assertTrue(baseline.is_file())
            execute({**base, "action": "rotate"})
            state = load_state(cfg, TERM)
            self.assertNotEqual(state.token, original_token)
            listing = subprocess.check_output(
                ["git", "--git-dir", str(remote), "ls-tree", "--name-only", "cal"], cwd=self.directory,
            ).decode().strip().splitlines()
            self.assertEqual(listing, [state.token + ".ics"])
            remote_bytes = subprocess.check_output(
                ["git", "--git-dir", str(remote), "show", f"cal:{state.token}.ics"], cwd=self.directory,
            )
            self.assertEqual(remote_bytes, baseline.read_bytes())
            for private_file in ("calendar.json", "schedule.db", "identity.json", "request.json"):
                self.assertNotIn(private_file.encode(), remote_bytes)

    def test_commit_failure_preserves_checkout_and_retry_publishes(self):
        from xjtu_calendar import subscribe
        remote = self.directory / 'commit-failure.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True, capture_output=True)
        cfg = self.prepare()
        base = {'home': str(cfg.home), 'term': TERM}
        with patch.dict('os.environ', {'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
                                     'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}):
            execute({**base, 'action': 'init', 'repo': remote.as_uri(), 'branch': 'cal',
                     'url_base': 'https://example.invalid/'})
            execute({**base, 'action': 'push'})
            baseline = cfg.subscribe_dir / f'last-{TERM}.ics'
            before = baseline.read_bytes()
            CourseInstance.update(location='New room').execute()
            self.prepare()
            real_git = subscribe._must_git
            def fail_commit(work, *args):
                if args[0] == 'commit':
                    raise RuntimeError('synthetic commit failure')
                return real_git(work, *args)
            with patch.object(subscribe, '_must_git', side_effect=fail_commit):
                with self.assertRaises(RuntimeError):
                    execute({**base, 'action': 'push'})
            self.assertEqual(baseline.read_bytes(), before)
            execute({**base, 'action': 'repair'})
            execute({**base, 'action': 'push'})
            self.assertNotEqual(baseline.read_bytes(), before)
            self.assertEqual(len(list(cfg.subscribe_dir.glob(f'work-{TERM}-failed-*/checkout'))), 1)
            state = load_state(cfg, TERM)
            remote_bytes = subprocess.check_output(['git', '--git-dir', str(remote), 'show', f'cal:{state.token}.ics'])
            self.assertEqual(remote_bytes, baseline.read_bytes())


if __name__ == "__main__":
    unittest.main()
