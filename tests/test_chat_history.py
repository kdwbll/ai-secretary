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
