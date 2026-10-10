from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from datetime import date

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.service import SecretaryService
from core.secretary.storage import LocalStorage


class ChatHistoryTests(TestCase):
    def make_service(self, root: Path) -> SecretaryService:
        database = Database(root / "data.db")
        memory = MemoryEngine(LocalStorage(root / "memory"), database)
        memory.initialize()
        models = Mock()
        models.complete.return_value = "记住了。"
        prompt_dir = root / "prompts"
        prompt_dir.mkdir()
        (prompt_dir / "chat.md").write_text("回答用户", encoding="utf-8")
        return SecretaryService(memory, database, models, prompt_dir)

    def test_history_can_delete_chat_and_its_tagged_memory(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            result = service.chat("我每天运动")

            history = service.chat_history()
            self.assertEqual(history[0]["id"], result["id"])
            self.assertEqual(history[0]["user_message"], "我每天运动")
            self.assertIn(f"对话 #{result['id']}", service.memory.storage.read_text("habits.md"))

            deleted = service.delete_chat(result["id"], delete_memory=True)
            self.assertGreaterEqual(deleted["removed_memories"], 2)
            self.assertEqual(service.chat_history(), [])
            self.assertNotIn(f"对话 #{result['id']}", service.memory.storage.read_text("habits.md"))
            self.assertNotIn("我每天运动", service.memory.storage.read_text(f"daily/{date.today().isoformat()}.md"))

    def test_deleting_history_only_preserves_memory(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            result = service.chat("我每天运动")
            service.delete_chat(result["id"], delete_memory=False)
            self.assertIn(f"对话 #{result['id']}", service.memory.storage.read_text("habits.md"))

    def test_existing_facts_mark_profile_as_completed(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.assertFalse(service.profile_status()["completed"])
            service.chat("我每天运动")
            service.chat("我的预算是每月三千元")
            service.chat("我喜欢音乐")
            self.assertTrue(service.profile_status()["completed"])

    def test_interview_completion_is_persisted(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.assertTrue(service.complete_interview()["completed"])
            self.assertTrue(service.profile_status()["completed"])

    def test_frequent_place_updates_interests_after_initial_profile(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.complete_interview()
            result = service.chat("我经常去春熙路玩")
            interests = service.memory.storage.read_text("interests.md")
            habits = service.memory.storage.read_text("habits.md")
            self.assertIn("## 常去地点", interests)
            self.assertIn("我经常去春熙路玩", interests)
            self.assertIn(f"对话 #{result['id']}", interests)
            self.assertNotIn("我经常去春熙路玩", habits)

    def test_health_question_is_not_saved_as_a_health_fact(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.chat("分析一下我的健康数据")
            self.assertNotIn("分析一下我的健康数据", service.memory.storage.read_text("health.md"))

    def test_relevant_uploaded_document_is_added_to_context(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)",
                    ("hash", "本科生综合素质评价办法.doc", "files/test.doc", "2026-10-10T12:00:00", "发展性评价包含创新创造与志愿服务"),
                )
            context = service._context("我最近要算综测")
            self.assertIn("本科生综合素质评价办法.doc", context)
            self.assertIn("发展性评价包含创新创造与志愿服务", context)
