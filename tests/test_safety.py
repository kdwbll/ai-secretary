from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.secretary.database import Database
from core.secretary.safety import ApprovalError, ApprovalService


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "second-brain.db")
        self.safety = ApprovalService(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_and_irreversible_actions_require_approval(self):
        with self.assertRaisesRegex(ApprovalError, "必须先获得审批"):
            self.safety.require("write", connector="calendar", action_type="calendar.create")
        self.assertIsNone(self.safety.require("read", connector="calendar"))

    def test_denial_and_duplicate_decision(self):
        item = self.safety.request("mail.send", "write", "发送邮件", connector="email", idempotency_key="deny-1")
        denied = self.safety.decide(item["id"], "deny")
        self.assertEqual(denied["status"], "denied")
        with self.assertRaisesRegex(ApprovalError, "不能重复提交"):
            self.safety.decide(item["id"], "approve")

    def test_expiry_blocks_execution(self):
        item = self.safety.request("calendar.create", "write", "创建日程", connector="calendar", idempotency_key="expired-1")
        with self.database.connect() as db:
            expired = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
            db.execute("UPDATE action_approvals SET expires_at=? WHERE id=?", (expired, item["id"]))
        self.assertEqual(self.safety.get(item["id"])["status"], "expired")
        with self.assertRaisesRegex(ApprovalError, "缺少有效审批"):
            self.safety.claim(item["id"], action_type="calendar.create", connector="calendar")

    def test_idempotent_request_and_single_execution(self):
        first = self.safety.request("mail.send", "write", "发送邮件", connector="email", idempotency_key="same")
        second = self.safety.request("mail.send", "write", "不应覆盖", connector="email", idempotency_key="same")
        self.assertEqual(first["id"], second["id"])
        self.safety.decide(first["id"], "approve", edited_payload={"subject": "已修改"})
        claimed = self.safety.claim(first["id"], action_type="mail.send", connector="email")
        self.assertEqual(claimed["exact_payload"], {"subject": "已修改"})
        with self.assertRaisesRegex(ApprovalError, "缺少有效审批"):
            self.safety.claim(first["id"], action_type="mail.send", connector="email")
        self.assertEqual(self.safety.finish(first["id"], success=True)["status"], "executed")

    def test_restart_preserves_pending_approval(self):
        item = self.safety.request("mail.send", "write", "发送邮件", connector="email", idempotency_key="restart")
        restarted = ApprovalService(Database(self.database.path))
        self.assertEqual(restarted.get(item["id"])["status"], "pending")
        restarted.decide(item["id"], "approve")
        self.assertEqual(restarted.claim(item["id"], action_type="mail.send", connector="email")["status"], "executing")

    def test_connector_revoke_disables_tasks_and_pending_approvals(self):
        with self.database.connect() as db:
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            goal_id = db.execute("INSERT INTO goals(title,created_at,updated_at) VALUES('测试',?,?)", (now, now)).lastrowid
            db.execute(
                "INSERT INTO tasks(goal_id,title,created_at,updated_at,schedule,event_source,enabled) VALUES(?,?,?,?,?,?,1)",
                (goal_id, "等邮件", now, now, "event", "email"),
            )
        approval = self.safety.request("mail.send", "write", "发送邮件", connector="email", idempotency_key="revoke")
        permission = self.safety.set_connector("email", False)
        self.assertFalse(permission["enabled"])
        self.assertEqual(self.safety.get(approval["id"])["status"], "revoked")
        self.assertEqual(self.database.rows("SELECT enabled FROM tasks")[0]["enabled"], 0)
        with self.assertRaisesRegex(ApprovalError, "权限已撤销"):
            self.safety.require("read", connector="email")

    def test_audit_chain_detects_tampering(self):
        item = self.safety.request("mail.send", "write", "发送邮件", connector="email", idempotency_key="audit")
        self.safety.decide(item["id"], "deny")
        self.assertTrue(self.safety.verify_audit_chain()["valid"])
        with self.database.connect() as db:
            db.execute("UPDATE action_audit SET details='{}' WHERE id=(SELECT MIN(id) FROM action_audit)")
        self.assertFalse(self.safety.verify_audit_chain()["valid"])


if __name__ == "__main__":
    unittest.main()
