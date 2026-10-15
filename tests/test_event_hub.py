from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from core.secretary.database import Database
from core.secretary.event_hub import EventHub
from core.secretary.memory import MemoryEngine
from core.secretary.service import SecretaryService
from core.secretary.storage import LocalStorage
from unittest.mock import Mock

class EventHubTests(TestCase):
    def test_identical_event_is_recorded_once(self):
        with TemporaryDirectory() as directory:
            hub = EventHub(Database(Path(directory) / "events.db"))
            first = hub.publish("sms", "pickup", {"text": "取件码 123"})
            second = hub.publish("sms", "pickup", {"text": "取件码 123"})
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["id"], second["id"])

    def test_sms_replay_does_not_repeat_side_effects(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "events.db")
            memory = MemoryEngine(LocalStorage(root / "memory"), database)
            memory.initialize()
            service = SecretaryService(memory, database, Mock(), root / "prompts")
            first = service.ingest_sms("取件码 123456", "快递")
            second = service.ingest_sms("取件码 123456", "快递")
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(len(database.rows("SELECT id FROM events WHERE source='sms'")), 1)
