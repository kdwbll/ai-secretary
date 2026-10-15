from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.actions import UsefulActionService
from core.secretary.database import Database
from core.secretary.safety import ApprovalError, ApprovalService


class UsefulActionTests(TestCase):
    def test_calendar_suggestion_requires_approval_and_reports_conflicts(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "actions.db")
            safety = ApprovalService(database)
            actions = UsefulActionService(database, safety)
            first = actions.suggest_calendar({
                "title": "第一次复查", "start_at": "2026-12-01T09:00:00+08:00", "end_at": "2026-12-01T10:00:00+08:00"
            }, idempotency_key="calendar-1")
            with self.assertRaisesRegex(ApprovalError, "缺少有效审批"):
                actions.execute_calendar(first["id"])
            safety.decide(first["id"], "approve")
            created = actions.execute_calendar(first["id"])
            self.assertEqual(created["title"], "第一次复查")
            with self.assertRaisesRegex(ApprovalError, "缺少有效审批"):
                actions.execute_calendar(first["id"])
            second = actions.suggest_calendar({
                "title": "时间冲突", "start_at": "2026-12-01T09:30:00+08:00", "end_at": "2026-12-01T10:30:00+08:00"
            }, idempotency_key="calendar-2")
            self.assertEqual(second["exact_payload"]["conflicts"][0]["title"], "第一次复查")

    def test_rejected_calendar_suggestion_is_not_repeated(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "actions.db")
            safety = ApprovalService(database)
            actions = UsefulActionService(database, safety)
            payload = {"title": "复习", "start_at": "2026-12-02T19:00:00+08:00", "end_at": "2026-12-02T20:00:00+08:00"}
            first = actions.suggest_calendar(payload)
            safety.decide(first["id"], "deny")
            repeated = actions.suggest_calendar(payload)
            self.assertEqual(repeated["id"], first["id"])
            self.assertEqual(repeated["status"], "denied")

    def test_email_draft_is_local_editable_and_never_sends(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "actions.db")
            actions = UsefulActionService(database, ApprovalService(database))
            draft = actions.create_draft(recipients=["doctor@example.com"], cc=[], subject="复查预约", body="您好")
            self.assertEqual(draft["status"], "draft")
            changed = actions.update_draft(draft["id"], {"body": "您好，我想预约复查。"})
            self.assertIn("预约复查", changed["body"])
            self.assertEqual(database.rows("SELECT COUNT(*) count FROM action_approvals")[0]["count"], 0)
            actions.delete_draft(draft["id"])
            self.assertEqual(actions.drafts(), [])
