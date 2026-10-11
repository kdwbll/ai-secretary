import json
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from core.secretary.connectors import html_to_text, parse_message
from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.service import SecretaryService
from core.secretary.storage import LocalStorage


class EmailConnectorTests(TestCase):
    def test_html_only_email_becomes_readable_text(self):
        message = EmailMessage()
        message["Subject"] = "课程通知"
        message["From"] = "teacher@example.com"
        message.set_content("<html><style>.x{display:none}</style><body><h1>课程调整</h1><p>周五改到 15:30。</p></body></html>", subtype="html")

        parsed = parse_message(message.as_bytes())

        self.assertEqual(parsed["subject"], "课程通知")
        self.assertIn("课程调整", parsed["body"])
        self.assertIn("周五改到 15:30", parsed["body"])
        self.assertNotIn("display:none", parsed["body"])

    def test_multipart_alternative_prefers_plain_text(self):
        message = EmailMessage()
        message.set_content("纯文本正文")
        message.add_alternative("<p>HTML 正文</p>", subtype="html")
        self.assertEqual(parse_message(message.as_bytes())["body"], "纯文本正文")

    def test_attachment_is_returned_but_not_mixed_into_body(self):
        message = EmailMessage()
        message.set_content("请查看附件。")
        message.add_attachment("姓名,成绩\n小周,95".encode(), maintype="text", subtype="csv", filename="成绩.csv")

        parsed = parse_message(message.as_bytes())

        self.assertEqual(parsed["body"], "请查看附件。")
        self.assertEqual(parsed["attachments"][0]["name"], "成绩.csv")
        self.assertIn(b"95", parsed["attachments"][0]["data"])

    def test_html_converter_decodes_entities_and_line_breaks(self):
        self.assertEqual(html_to_text("<p>A&amp;B</p><p>第二行</p>"), "A&B\n\n第二行")


class EmailIngestionTests(TestCase):
    def test_body_and_attachments_are_searchable_after_ingestion(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            service = SecretaryService(memory, database, Mock(), root / "prompts")
            service.ingest_email(
                "奖学金材料",
                "office@example.com",
                "请在十月十五日前提交申请表。",
                [{"name": "申请表.docx", "hash": "abc", "url": "/api/files/abc/content"}],
            )

            payload = json.loads(database.rows("SELECT payload FROM events WHERE source='email'")[0]["payload"])
            self.assertIn("十月十五日", payload["body"])
            self.assertEqual(payload["attachments"][0]["name"], "申请表.docx")
            context = service._email_context("最近的邮件说了什么")
            self.assertIn("十月十五日", context)
            self.assertIn("申请表.docx", context)

    def test_resync_updates_existing_event_instead_of_duplicating_it(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            service = SecretaryService(memory, database, Mock(), root / "prompts")
            service.ingest_email("通知", "office@example.com", "旧正文", message_uid="mail-1")
            result = service.ingest_email("通知", "office@example.com", "更新后的完整正文", message_uid="mail-1")

            self.assertTrue(result["updated"])
            rows = database.rows("SELECT payload FROM events WHERE source='email'")
            self.assertEqual(len(rows), 1)
            self.assertIn("完整正文", json.loads(rows[0]["payload"])["body"])
