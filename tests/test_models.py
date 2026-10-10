from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.secretary.database import Database
from core.secretary.models import ModelRouter, Route


class RouterTests(unittest.TestCase):
    def test_provider_and_route_round_trip(self):
        with TemporaryDirectory() as temp:
            router = ModelRouter(Database(Path(temp) / "db.sqlite"))
            router.save_provider("local", "http://localhost:11434/v1", "", ["qwen2.5"])
            router.set_route(Route("fast", "local", "qwen2.5"))
            self.assertEqual(router.route("fast").model, "qwen2.5")
            self.assertEqual(router.providers()[0]["models"], ["qwen2.5"])


if __name__ == "__main__":
    unittest.main()
