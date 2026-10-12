import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.reports import ReportService
from core.secretary.service import SecretaryService
from core.secretary.storage import LocalStorage


class CalendarSyncTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "data.db")
        self.memory = MemoryEngine(LocalStorage(root / "memory"), self.database)
        self.memory.initialize()
        self.service = SecretaryService(self.memory, self.database, Mock(), root / "prompts")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def event(title="团队例会", external_id="42:1760058000000"):
        return {
            "external_id": external_id, "title": title,
            "start_at": "2026-10-10T09:00:00+08:00", "end_at": "2026-10-10T10:00:00+08:00",
            "all_day": False, "location": "会议室 A", "description": "周会", "calendar_name": "工作",
        }

    def test_sync_upserts_instance_and_marks_missing_window_item_stale(self):
        result = self.service.ingest_calendar_events([self.event()], "2026-10-09T00:00:00+08:00", "2026-10-11T00:00:00+08:00")
        self.assertEqual(result, {"created": 1, "updated": 0, "stale": 0, "events": 1})

        result = self.service.ingest_calendar_events([self.event("更新后的例会")], "2026-10-09T00:00:00+08:00", "2026-10-11T00:00:00+08:00")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.database.rows("SELECT COUNT(*) AS count FROM events WHERE source='calendar'")[0]["count"], 1)
        payload = json.loads(self.database.rows("SELECT payload FROM events WHERE source='calendar'")[0]["payload"])
        self.assertEqual(payload["title"], "更新后的例会")

        result = self.service.ingest_calendar_events([], "2026-10-09T00:00:00+08:00", "2026-10-11T00:00:00+08:00")
        self.assertEqual(result["stale"], 1)
        self.assertEqual(self.database.rows("SELECT status FROM events WHERE source='calendar'")[0]["status"], "stale")

    def test_calendar_is_available_to_schedule_questions_but_not_unrelated_chat(self):
        self.service.ingest_calendar_events([self.event()], "2026-10-09T00:00:00+08:00", "2026-10-10T23:00:00+08:00")
        with patch("core.secretary.service.datetime") as clock:
            from datetime import datetime as real_datetime
            clock.now.return_value = real_datetime.fromisoformat("2026-10-10T08:00:00+08:00")
            clock.fromisoformat.side_effect = real_datetime.fromisoformat
            context = self.service._calendar_context("今天有什么安排？")
            self.assertIn("团队例会", context)
            self.assertIn("会议室 A", context)
            self.assertEqual(self.service._calendar_context("帮我写一段文案"), "")

    def test_morning_report_lists_todays_calendar(self):
        self.service.ingest_calendar_events([self.event()], "2026-10-09T00:00:00+08:00", "2026-10-11T00:00:00+08:00")
        with patch("core.secretary.reports.datetime") as clock:
            from datetime import datetime as real_datetime
            clock.now.return_value = real_datetime.fromisoformat("2026-10-10T07:30:00+08:00")
            clock.fromisoformat.side_effect = real_datetime.fromisoformat
            report = ReportService(self.memory, self.database).morning()
        self.assertIn("## 今日日程", report)
        self.assertIn("09:00 团队例会（会议室 A）", report)
