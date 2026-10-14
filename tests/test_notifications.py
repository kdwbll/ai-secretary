from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.database import Database
from core.secretary.notifications import NotificationService


class NotificationTests(TestCase):
    def test_same_kind_is_grouped_within_configured_window(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            database.set_setting("notifications_enabled", "1")
            database.set_setting("notification_dedup_minutes", "60")
            service = NotificationService(database)

            self.assertTrue(service._may_alert("weekly"))
            service.publish("weekly", "每周整理", "第一条")
            self.assertFalse(service._may_alert("weekly"))

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

    def test_database_upgrade_removes_old_system_service_notifications(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.db"
            Database(path)
            with sqlite3.connect(path) as db:
                db.execute(
                    "INSERT INTO events(created_at,source,kind,payload) VALUES(?,?,?,?)",
                    ("2026-10-12T20:36:22", "notification", "notification", json.dumps({
                        "title": "应用通知", "raw": "“短信”正在运行 点按即可了解详情或停止应用。",
                    }, ensure_ascii=False)),
                )
                db.execute("DELETE FROM schema_migrations WHERE version=9")
                db.execute("PRAGMA user_version=8")
            Database(path)
            self.assertEqual(Database(path).rows("SELECT id FROM events WHERE source='notification'"), [])
