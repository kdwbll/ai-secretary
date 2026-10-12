from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.models import ModelNetworkError
from core.secretary.secrets import SecretStore
from core.secretary.service import SecretaryService
from core.secretary.storage import LocalStorage


class TimeLocationStreamTests(TestCase):
    def make_service(self, root: Path):
        database = Database(root / "data.db")
        memory = MemoryEngine(LocalStorage(root / "memory"), database)
        memory.initialize()
        models = Mock()
        models.complete.return_value = '{"show":true,"query":"附近咖啡店","mode":"nearby"}'
        models.stream_complete.return_value = iter(["今天", "是周日。"])
        prompts = root / "prompts"
        prompts.mkdir()
        (prompts / "chat.md").write_text("回答用户", encoding="utf-8")
        return SecretaryService(memory, database, models, prompts)

    def test_shanghai_time_context_contains_date_weekday_and_time(self):
        now = datetime(2026, 10, 11, 14, 5, 6, tzinfo=ZoneInfo("Asia/Shanghai"))
        context = SecretaryService._time_context(now)
        self.assertIn("2026年10月11日", context)
        self.assertIn("星期日", context)
        self.assertIn("14:05:06", context)
        self.assertIn("Asia/Shanghai", context)

    def test_location_is_only_added_for_location_question(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.database.set_setting("location_enabled", "1")
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO locations(source,label,latitude,longitude,enabled,updated_at) VALUES(?,?,?,?,?,?)",
                    ("default", "春熙路", 30.657, 104.066, 1, "2026-10-11 12:00:00"),
                )
            self.assertNotIn("春熙路", service._context("帮我写个总结"))
            plan = service._location_plan("附近有什么咖啡店")
            context = service._context("附近有什么咖啡店", location_plan=plan)
            self.assertIn("春熙路", context)
            self.assertIn("前端会在这条回答下方自动插入高德地图卡片", context)
            self.assertIn("未配置高德 Web 服务 API Key", context)
            self.assertEqual(service._map_attachment(plan)[0]["mode"], "nearby")

    def test_generic_current_location_uses_reverse_geocoding_for_model_context(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.secret_store = Mock()
            service.secret_store.decrypt.return_value = "web-service-key"
            service.database.set_setting("map_web_service_key", "encrypted-key")
            with service.database.connect() as db:
                db.execute(
                    "INSERT INTO locations(source,label,latitude,longitude,enabled,updated_at) VALUES(?,?,?,?,?,?)",
                    ("android", "Android", 30.765198, 103.981348, 1, "2026-10-12 11:42:35"),
                )
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = '{"status":"1","regeocode":{"formatted_address":"四川省成都市郫都区犀浦街道", "pois":[{"name":"西南交通大学犀浦校区","distance":"120"}]}}'.encode()
            with patch("core.secretary.service.urlopen", return_value=response) as request:
                context = service._amap_poi_context({"query": "我的位置", "mode": "nearby"})
            self.assertIn("四川省成都市郫都区犀浦街道", context)
            self.assertIn("西南交通大学犀浦校区（120 米）", context)
            self.assertIn("v3/geocode/regeo", request.call_args.args[0])

    def test_stream_persists_title_and_is_searchable(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            events = list(service.chat_stream("今天周几？请直接回答"))
            self.assertEqual([item["event"] for item in events], ["start", "delta", "delta", "done"])
            self.assertEqual(events[-1]["data"]["answer"], "今天是周日。")
            history = service.chat_history(query="今天周几")
            self.assertEqual(history[0]["title"], "今天周几")

    def test_stream_failure_is_persisted_instead_of_staying_unfinished(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            service.models.stream_complete.side_effect = ModelNetworkError("offline")

            with self.assertRaises(ModelNetworkError):
                list(service.chat_stream("在吗"))

            history = service.chat_history()
            self.assertEqual(history[0]["assistant_message"], ModelNetworkError.user_message)
            self.assertEqual(history[0]["attachments"]["warnings"], [ModelNetworkError.user_message])

    def test_secret_store_encrypts_and_authenticates_values(self):
        with TemporaryDirectory() as directory:
            store = SecretStore(Path(directory) / ".key")
            encrypted = store.encrypt("private-api-key")
            self.assertTrue(encrypted.startswith("enc:v1:"))
            self.assertNotIn("private-api-key", encrypted)
            self.assertEqual(store.decrypt(encrypted), "private-api-key")
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                store.decrypt(encrypted[:-2] + "AA")
