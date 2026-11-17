import datetime
import http.client
import socket
import threading
import time
import tempfile
import unittest
from pathlib import Path

from icalendar import Calendar
from schedule.calendar_export import build_calendar
from schedule.calendar_subscription import CalendarSubscription, load_token, is_lan_address
from schedule.schedule_database import Course, CourseInstance, Exam
from schedule.schedule_service import ScheduleService

TEST_DOMAIN = "schedule"
TEST_REGRESSION = True
STAMP = datetime.datetime(2026, 11, 17, tzinfo=datetime.timezone.utc)


class CalendarExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = ScheduleService(str(Path(self.tmp.name) / "schedule.db"))
        self.addCleanup(self.service.database.close)
        self.service.setTermInfo("2026-2027-1", "2026-09-07", current=True)
        self.course = Course.create(name="建筑设计")
        self.fields = dict(course=self.course, name="建筑设计", week_number=1, day_of_week=1,
                           start_time=1, end_time=2, location="教室 A", term_number="2026-2027-1")
        CourseInstance.create(**self.fields)

    def events(self, **kw):
        return Calendar.from_ical(build_calendar(self.service, stamp=STAMP, **kw)).walk("VEVENT")

    def test_reuses_course_time_location_and_alarm(self):
        event = self.events()[0]
        self.assertEqual(str(event["SUMMARY"]), "建筑设计")
        self.assertEqual(str(event["LOCATION"]), "教室 A")
        self.assertEqual(event.decoded("DTSTART").date(), datetime.date(2026, 9, 7))
        self.assertEqual(event.decoded("DTSTART").utcoffset(), datetime.timedelta(hours=8))
        self.assertEqual(event.walk("VALARM")[0].decoded("TRIGGER"), datetime.timedelta(minutes=-15))
        self.assertTrue(event.get("UID"))
        self.assertEqual(event.decoded("DTSTAMP"), STAMP)

    def test_uid_survives_reimport_and_location_edit(self):
        uid = self.events()[0]["UID"]
        CourseInstance.delete().execute()
        CourseInstance.create(**{**self.fields, "location": "教室 B"})
        self.assertEqual(self.events()[0]["UID"], uid)
        self.assertNotEqual(self.events(uid_namespace="other-account")[0]["UID"], uid)

    def test_duplicate_slots_have_unique_uids(self):
        CourseInstance.create(**self.fields)
        self.assertEqual(len({str(e["UID"]) for e in self.events()}), 2)

    def test_holiday_exclusion_and_alarm_option(self):
        self.assertEqual(self.events(ignore_holidays=[datetime.date(2026, 9, 7)]), [])
        self.assertEqual(self.events(set_alarm=False)[0].walk("VALARM"), [])

    def test_nullable_exam_seat_and_exact_time(self):
        Exam.create(course=self.course, name="建筑考试", location=None, seat_number=None,
                    week_number=2, day_of_week=2, start_time=1, end_time=2,
                    start_exact_time=datetime.time(9, 30), end_exact_time=datetime.time(11, 10),
                    term_number="2026-2027-1")
        exam = self.events()[-1]
        self.assertEqual(exam.decoded("DTSTART").hour, 9)
        self.assertEqual(exam.decoded("DTSTART").minute, 30)
        self.assertEqual(exam.walk("VALARM")[0].decoded("TRIGGER"), datetime.timedelta(minutes=-30))

    def test_database_proxy_cannot_leak_another_account(self):
        other = ScheduleService(str(Path(self.tmp.name) / "other.db"))
        self.addCleanup(other.database.close)
        other.setTermInfo("2026-2027-1", "2026-09-07", current=True)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(Calendar.from_ical(build_calendar(other)).walk("VEVENT"), [])

    def test_missing_term_fails_instead_of_publishing_empty_feed(self):
        self.service.setCurrentTerm("missing")
        with self.assertRaises(ValueError):
            self.events()


class SubscriptionServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = load_token(self.tmp.name)
        self.server = CalendarSubscription()
        self.addCleanup(self.server.stop)
        self.data = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
        self.url = self.server.start("127.0.0.1", 0, self.token, self.data)
        self.port = self.server._server.server_port
        self.path = f"/{self.token}/calendar.ics"

    def request(self, method="GET", path=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            client.request(method, path or self.path, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def test_get_head_etag_and_content_update(self):
        status, headers, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(data, self.data)
        self.assertIn("text/calendar", headers["Content-Type"])
        self.assertEqual(self.request("HEAD")[2], b"")
        self.assertEqual(self.request(headers={"If-None-Match": headers["ETag"]})[0], 304)
        updated = self.data.replace(b"VERSION:2.0", b"VERSION:2.0\r\nX-WR-CALNAME:Updated")
        self.server.update(updated)
        self.assertEqual(self.request(headers={"If-None-Match": headers["ETag"]})[2], updated)

    def test_only_exact_secret_path_is_served(self):
        for path in ("/", "/calendar.ics", "/../../schedule.db", self.path + "?x=1"):
            self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request("POST")[0], 501)

    def test_token_is_stable_per_account(self):
        self.assertEqual(load_token(self.tmp.name), self.token)
        with tempfile.TemporaryDirectory() as other:
            self.assertNotEqual(load_token(other), self.token)

    def test_stop_releases_listener_and_payload(self):
        self.server.stop()
        self.server.stop()
        self.assertFalse(self.server.running)
        self.assertIsNone(self.server._data)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=0.3)

    def test_invalid_update_keeps_last_valid_feed(self):
        with self.assertRaises(ValueError):
            self.server.update(b"bad")
        self.assertEqual(self.request()[2], self.data)

    def test_port_conflict_does_not_start_second_server(self):
        other = CalendarSubscription()
        self.addCleanup(other.stop)
        with self.assertRaises(OSError):
            other.start("127.0.0.1", self.port, self.token, self.data)
        self.assertFalse(other.running)

    def test_slow_client_does_not_block_other_clients_or_stop(self):
        client = socket.create_connection(("127.0.0.1", self.port), timeout=1)
        self.addCleanup(client.close)
        client.sendall(b"GET /")
        # The partial request must not occupy the listener.
        self.assertEqual(self.request()[0], 200)
        finished = threading.Event()
        stopper = threading.Thread(target=lambda: (self.server.stop(), finished.set()), daemon=True)
        started = time.monotonic()
        stopper.start()
        while not finished.wait(.05) and time.monotonic() - started < 1:
            try:
                client.sendall(b"a")
            except OSError:
                break
        self.assertTrue(finished.wait(1), "stop must interrupt a drip-fed connection")
        stopper.join(1)
        self.assertFalse(self.server.running)

    def test_absolute_deadline_disconnects_drip_fed_request(self):
        self.server._server.request_deadline = .25
        client = socket.create_connection(("127.0.0.1", self.port), timeout=1)
        self.addCleanup(client.close)
        client.sendall(b"GET /")
        started = time.monotonic()
        disconnected = False
        while time.monotonic() - started < 1.5:
            try:
                client.sendall(b"a")
            except OSError:
                disconnected = True
                break
            time.sleep(.05)
        self.assertTrue(disconnected, "traffic must not reset the total request deadline")
        self.assertEqual(self.request()[0], 200)

    def test_restart_on_same_port_preserves_subscription_url(self):
        self.assertEqual(self.request()[0], 200)
        self.server.stop()
        self.assertEqual(self.server.start("127.0.0.1", self.port, self.token, self.data), self.url)
        self.assertEqual(self.request()[0], 200)

    def test_active_client_limit_is_bounded(self):
        clients = []
        try:
            for _ in range(12):
                client = socket.create_connection(("127.0.0.1", self.port), timeout=1)
                clients.append(client)
                try:
                    client.sendall(b"GET /")
                except OSError:
                    pass
            time.sleep(.1)
            with self.server._server._request_lock:
                self.assertLessEqual(len(self.server._server._requests), 8)
            self.server.stop()
        finally:
            for client in clients:
                client.close()

    def test_rejects_public_and_wildcard_bind_addresses(self):
        for value in ("0.0.0.0", "8.8.8.8", "::", "not-an-ip"):
            self.assertFalse(is_lan_address(value))
        self.assertTrue(is_lan_address("192.168.1.10"))


if __name__ == "__main__":
    unittest.main()
