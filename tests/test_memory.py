from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import unittest

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.storage import LocalStorage


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Database(root / "data.db")
        self.memory = MemoryEngine(LocalStorage(root / "memory"), self.db)
        self.memory.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_front_matter_and_index(self):
        doc = self.memory.parse("me.md")
        self.assertEqual(doc.metadata["type"], "user")
        self.assertIn("me.md", self.memory.storage.read_text("index.md"))

    def test_rewrite_instead_of_append(self):
        self.memory.upsert_fact("habits.md", "作息", "通常 23:00 睡", "测试")
        self.memory.upsert_fact("habits.md", "作息", "通常 22:30 睡", "测试", old_fact="通常 23:00 睡")
        text = self.memory.storage.read_text("habits.md")
        self.assertNotIn("23:00 睡", text)
        self.assertEqual(text.count("22:30 睡"), 1)

    def test_condition_and_inference_are_preserved(self):
        self.memory.upsert_fact("habits.md", "饮食", "晚餐吃得较晚", "测试", inferred=True, condition="加班日")
        text = self.memory.storage.read_text("habits.md")
        self.assertIn("(推测)", text)
        self.assertIn("(条件: 加班日)", text)

    def test_forget_removes_all_copies_and_adds_rule(self):
        for path, section in (("me.md", "基本信息"), ("health.md", "当前状况")):
            self.memory.upsert_fact(path, section, "对花生过敏", "测试")
        removed = self.memory.forget("花生")
        self.assertEqual(removed, 2)
        self.assertNotIn("花生", self.memory.storage.read_text("health.md"))
        self.assertIn("不再记录：花生", self.memory.storage.read_text("me.md"))

    def test_undo_restores_previous_text(self):
        before = self.memory.storage.read_text("finance.md")
        self.memory.upsert_fact("finance.md", "收支与预算", "每月预算 3000 元", "测试")
        mutation = self.db.rows("SELECT id FROM mutations WHERE path='finance.md' ORDER BY id DESC LIMIT 1")[0]["id"]
        self.memory.undo(mutation)
        self.assertEqual(self.memory.storage.read_text("finance.md"), before)

    def test_search_skips_a_non_utf8_note(self):
        (self.memory.storage.root / "broken.md").write_bytes(b"\x96not utf8")
        results = self.memory.search("测试")
        self.assertNotIn("broken.md", [item["path"] for item in results])

    def test_current_daily_note_repairs_invalid_utf8_without_blocking_startup(self):
        daily = self.memory.ensure_daily()
        path = self.memory.storage.root / daily.path
        path.write_bytes(path.read_bytes() + b"\n\x96damaged tail")
        repaired = self.memory.ensure_daily()
        self.assertIn("damaged tail", repaired.body)
        self.assertTrue(list(path.parent.glob(path.name + ".invalid-utf8-*.bak")))

    def test_concurrent_daily_writes_do_not_lose_events_or_temp_files(self):
        messages = [f"并发事件-{index}" for index in range(20)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.memory.append_daily, messages))
        daily = self.memory.ensure_daily()
        text = self.memory.storage.read_text(daily.path)
        for message in messages:
            self.assertIn(message, text)
        self.assertFalse(list((self.memory.storage.root / "daily").glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
