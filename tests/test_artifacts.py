from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.artifacts import ArtifactConflict, ArtifactService, safe_file_preview
from core.secretary.database import Database


class ArtifactTests(TestCase):
    def test_versions_preserve_user_edits_and_require_refresh_confirmation(self):
        with TemporaryDirectory() as directory:
            service = ArtifactService(Database(Path(directory) / "artifacts.db"))
            created = service.create("plan", "复查计划", "# 第一步", source="chat #1")
            edited = service.update(created["id"], "# 用户修改", base_version=1, actor="user")
            self.assertEqual(edited["current_version"], 2)
            self.assertTrue(edited["user_edited"])
            with self.assertRaisesRegex(ArtifactConflict, "需要确认"):
                service.update(created["id"], "# 助手刷新", base_version=2, actor="assistant")
            refreshed = service.update(created["id"], "# 助手刷新", base_version=2, actor="assistant", confirm_overwrite=True)
            self.assertEqual(refreshed["current_version"], 3)
            self.assertEqual(len(refreshed["versions"]), 3)

    def test_stale_editor_cannot_overwrite_new_version(self):
        with TemporaryDirectory() as directory:
            service = ArtifactService(Database(Path(directory) / "artifacts.db"))
            item = service.create("checklist", "清单", "- [ ] 一项")
            service.update(item["id"], "- [x] 一项", base_version=1)
            with self.assertRaisesRegex(ArtifactConflict, "已有新版本"):
                service.update(item["id"], "旧页面内容", base_version=1)

    def test_safe_preview_escapes_active_html(self):
        preview = safe_file_preview("demo.html", '<script>alert(1)</script><img src="https://tracker">')
        self.assertNotIn("<script>", preview)
        self.assertNotIn("<img src=", preview)
        self.assertIn("default-src 'none'", preview)

    def test_delete_artifact_does_not_delete_goal_or_memory(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "artifacts.db")
            now = "2026-10-15T12:00:00+08:00"
            with database.connect() as db:
                goal_id = db.execute("INSERT INTO goals(title,created_at,updated_at) VALUES('目标',?,?)", (now, now)).lastrowid
            service = ArtifactService(database)
            item = service.create("budget", "预算", "交通 100", goal_id=goal_id)
            service.delete(item["id"])
            self.assertEqual(database.rows("SELECT title FROM goals WHERE id=?", (goal_id,))[0]["title"], "目标")
