from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from datetime import date

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.models import ModelNetworkError
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

    def test_chat_state_changes_when_the_latest_conversation_changes(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.assertEqual(service.chat_state()["signature"], "empty")
            service.chat("帮我安排今天")
            signature = service.chat_state()["signature"]
            self.assertNotEqual(signature, "empty")
            service.chat("再补充一项")
            self.assertNotEqual(service.chat_state()["signature"], signature)

    def test_guided_follow_up_is_saved_as_a_structured_attachment(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.models.complete.return_value = "先处理最要紧的一项。\n\n[[guide: 你想先整理哪一份？ | 今晚待办 | 本周清单]]"

            result = service.chat("最近有什么要紧的事")

            self.assertNotIn("[[guide:", result["answer"])
            self.assertEqual(result["attachments"]["guidance"], {
                "question": "你想先整理哪一份？", "options": ["今晚待办", "本周清单"],
            })
            self.assertEqual(service.chat_history()[0]["attachments"]["guidance"]["options"], ["今晚待办", "本周清单"])

    def test_system_service_notification_is_not_saved(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            result = service.ingest_notification(
                "com.android.mms", "“短信”正在运行", "点按即可了解详情或停止应用。"
            )
            self.assertTrue(result["ignored"])
            events = service.database.rows("SELECT id FROM events WHERE source='notification'")
            self.assertEqual(events, [])

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

    def test_chat_attachment_is_sent_to_model_and_persisted(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)",
                    ("doc-hash", "报名须知.docx", "files/2026-10/doc.docx", "2026-10-11T12:00:00", "报名截止日期为十月二十日"),
                )
            result = service.chat("帮我看看", file_hashes=["doc-hash"], file_note="重点看截止日期")
            prompt = service.models.complete.call_args.args[1][0]["content"]
            self.assertIn("重点看截止日期", prompt)
            self.assertIn("报名截止日期为十月二十日", prompt)
            self.assertEqual(result["attachments"]["user_files"][0]["name"], "报名须知.docx")
            self.assertEqual(service.chat_history()[0]["attachments"]["file_note"], "重点看截止日期")

    def test_photo_question_returns_matching_uploaded_image(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)",
                    ("photo-hash", "杭州旅行.jpg", "files/2026-10/photo.jpg", "2026-10-11T12:00:00", "西湖边拍摄的旅行照片"),
                )
            result = service.chat("给我看看之前去杭州玩拍的照片")
            photo = result["attachments"]["assistant_files"][0]
            self.assertEqual(photo["hash"], "photo-hash")
            self.assertEqual(photo["kind"], "image")

    def test_analyzing_current_image_does_not_return_history_images(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)",
                    ("old-photo", "旧照片.jpg", "files/2026-10/old.jpg", "2026-10-10T12:00:00", "一张旧照片"),
                )
                db.execute(
                    "INSERT INTO files(hash,original_name,stored_path,created_at,extracted_text) VALUES(?,?,?,?,?)",
                    ("current-photo", "刚上传.jpg", "files/2026-10/current.jpg", "2026-10-11T12:00:00", "本轮图片"),
                )
            result = service.chat("分析一下这个图片", file_hashes=["current-photo"])
            self.assertEqual(result["attachments"]["assistant_files"], [])
            self.assertEqual(result["attachments"]["user_files"][0]["hash"], "current-photo")
            with service.database.connect() as db:
                db.execute(
                    "UPDATE chat_messages SET attachments=? WHERE id=?",
                    ('{"assistant_files":[{"hash":"old-photo"}]}', result["id"]),
                )
            self.assertEqual(service.chat_history()[0]["attachments"]["assistant_files"], [])

    def test_apple_account_question_gets_official_link(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            result = service.chat("哪里注册 Apple 账户？")
            self.assertIn("https://account.apple.com/", result["answer"])
            self.assertEqual(result["attachments"]["links"][0]["source"], "Apple 官方")

    def test_memory_write_failure_is_visible_and_persisted(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.memory.append_daily = Mock(side_effect=PermissionError("read only"))
            result = service.chat("帮我制定今天的计划")
            self.assertIn("记忆写入失败", result["attachments"]["warnings"][0])
            history = service.chat_history()
            self.assertEqual(history[0]["attachments"]["warnings"], result["attachments"]["warnings"])

    def test_memory_retry_resumes_after_index_failure_without_duplicate_daily_entry(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            original = service.memory.rebuild_index
            service.memory.rebuild_index = Mock(side_effect=PermissionError("read only"))
            result = service.chat("帮我制定今天的计划")
            self.assertEqual(result["attachments"]["memory_status"], "failed")
            service.memory.rebuild_index = original
            self.assertTrue(service.retry_chat_memory(result["id"])["saved"])
            daily = service.memory.storage.read_text(f"daily/{date.today().isoformat()}.md")
            self.assertEqual(daily.count(f"对话 #{result['id']})"), 1)
            self.assertEqual(service.models.complete.call_count, 1)
            self.assertEqual(service.chat_history()[0]["attachments"]["warnings"], [])
            with self.assertRaises(ValueError):
                service.retry_chat_memory(result["id"])

    def test_non_stream_failure_is_persisted_instead_of_staying_unfinished(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.models.complete.side_effect = ModelNetworkError("offline")

            with self.assertRaises(ModelNetworkError):
                service.chat("帮我总结今天")

            history = service.chat_history()
            self.assertEqual(history[0]["assistant_message"], ModelNetworkError.user_message)
            self.assertEqual(history[0]["attachments"]["warnings"], [ModelNetworkError.user_message])
