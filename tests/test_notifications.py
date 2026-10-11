from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.database import Database
from core.secretary.notifications import NotificationService


class NotificationTests(TestCase):
    def test_android_notification_keeps_full_markdown_body(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            service = NotificationService(database)
            body = "# 每周整理报告\n\n" + "- 完成一项重要任务。\n" * 80

            notification_id = service.publish("weekly", "每周整理", body)
            rows = service.since()

            self.assertEqual(rows[0]["id"], notification_id)
            self.assertEqual(rows[0]["kind"], "weekly")
            self.assertEqual(rows[0]["body"], body.strip())
            self.assertGreater(len(rows[0]["body"]), 300)

    def test_notification_body_has_a_safe_storage_limit(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            service = NotificationService(database)

            service.publish("weekly", "每周整理", "内容" * 20_000)

            self.assertEqual(len(service.since()[0]["body"]), 20_000)
