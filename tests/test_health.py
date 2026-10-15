from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.secretary.database import Database
from core.secretary.health import HealthService
from core.secretary.memory import MemoryEngine
from core.secretary.storage import LocalStorage


class HealthTests(unittest.TestCase):
    def make_service(self, root: Path) -> HealthService:
        database = Database(root / "data.db")
        memory = MemoryEngine(LocalStorage(root / "memory"), database)
        memory.initialize()
        return HealthService(database, memory)

    def test_import_generic_health_csv_and_deduplicate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = self.make_service(root)
            source = root / "mi-fitness.csv"
            source.write_text("date,steps,heart_rate,sleep_hours\n2026-10-09,8200,72,7.5\n", encoding="utf-8")
            first = service.import_file(source, source.name)
            second = service.import_file(source, source.name)
            self.assertEqual(first["imported"], 3)
            self.assertEqual(second["imported"], 0)
            summary = service.summary(14)
            steps = next(item for item in summary["series"] if item["metric"] == "steps")
            self.assertEqual(steps["latest"], 8200)
            self.assertIn("小米运动/通用导入", service.memory.storage.read_text("health.md"))

    def test_import_apple_health_xml(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = self.make_service(root)
            source = root / "export.xml"
            source.write_text(
                '<?xml version="1.0"?><HealthData><Record type="HKQuantityTypeIdentifierStepCount" '
                'sourceName="iPhone" unit="count" value="1234" startDate="2026-10-10 08:00:00 +0800" '
                'endDate="2026-10-10 09:00:00 +0800"/></HealthData>',
                encoding="utf-8",
            )
            result = service.import_file(source, source.name)
            self.assertEqual(result["source"], "Apple 健康")
            self.assertEqual(result["imported"], 1)

    def test_sync_android_health_samples_is_idempotent(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            samples = [{
                "external_id": "steps-2026-10-15", "recorded_at": "2026-10-15T21:00:00+08:00",
                "metric": "steps", "value": 7654, "unit": "步",
            }]
            first = service.sync_samples(samples)
            second = service.sync_samples(samples)
            self.assertEqual(first["imported"], 1)
            self.assertEqual(second["imported"], 0)
            self.assertEqual(first["latest"], "2026-10-15T21:00:00+08:00")
            self.assertIn("Android Health Connect", service.memory.storage.read_text("health.md"))
            samples[0]["value"] = 8001
            self.assertEqual(service.sync_samples(samples)["imported"], 1)
            self.assertEqual(service.summary(14)["series"][0]["latest"], 8001)


if __name__ == "__main__":
    unittest.main()
