import unittest

from app.threads.NoticeThread import NoticeThread
from notification import NotificationManager

TEST_DOMAIN = "qt-ui"
TEST_REGRESSION = True


class NoticeThreadStatusTest(unittest.TestCase):
    def test_skipped_source_does_not_emit_crawl_error(self):
        manager = NotificationManager(["test/unknown"])
        thread = NoticeThread(manager, session=object())
        errors = []
        notices = []
        finished = []
        thread.error.connect(lambda title, detail: errors.append((title, detail)))
        thread.notices.connect(notices.append)
        thread.hasFinished.connect(lambda: finished.append(True))

        thread.run()

        self.assertEqual(errors, [])
        self.assertEqual(notices, [[]])
        self.assertEqual(finished, [True])
        self.assertEqual(manager.last_errors, {})
        self.assertIn("test/unknown", manager.last_skipped)


if __name__ == "__main__":
    unittest.main()
