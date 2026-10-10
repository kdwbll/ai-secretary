from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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

    def test_provider_consumption_level_round_trip(self):
        with TemporaryDirectory() as temp:
            router = ModelRouter(Database(Path(temp) / "db.sqlite"))
            router.save_provider("deep", "https://example.com/v1", "key", ["model"], consumption_level="high")
            self.assertEqual(router.providers()[0]["consumption_level"], "high")

    def test_blank_key_does_not_replace_existing_secret(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("cloud", "https://one/v1", "kept-secret", ["a"])
            router.save_provider("cloud", "https://two/v1", "", ["b"])
            with database.connect() as db:
                secret = db.execute("SELECT api_key FROM providers WHERE name='cloud'").fetchone()[0]
            self.assertEqual(secret, "kept-secret")

    def test_delete_provider_clears_routes_but_keeps_other_providers(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("remove", "https://one/v1", "a", ["m1"])
            router.save_provider("keep", "https://two/v1", "b", ["m2"])
            router.set_route(Route("smart", "remove", "m1"))
            provider_id = next(p["id"] for p in router.providers() if p["name"] == "remove")
            self.assertEqual(router.delete_provider(provider_id), "remove")
            self.assertIsNone(router.route("smart"))
            self.assertEqual([p["name"] for p in router.providers()], ["keep"])

    def test_per_chat_model_override(self):
        with TemporaryDirectory() as temp:
            router = ModelRouter(Database(Path(temp) / "db.sqlite"))
            router.save_provider("one", "http://one/v1", "a", ["default"])
            router.save_provider("two", "http://two/v1", "b", ["chosen"])
            router.set_route(Route("smart", "one", "default"))
            with patch.object(router, "_openai_call", return_value="ok") as call:
                self.assertEqual(router.complete("smart", [], provider="two", model="chosen"), "ok")
                self.assertEqual(call.call_args.args[1:3], ("two", "chosen"))

    def test_email_account_schema_does_not_expose_secret_in_listing_query(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            with database.connect() as db:
                db.execute("INSERT INTO email_accounts(name,host,username,authorization_code) VALUES(?,?,?,?)", ("QQ", "imap.qq.com", "demo@qq.com", "secret"))
            rows = database.rows("SELECT id,name,host,port,username,enabled,last_sync FROM email_accounts")
            self.assertNotIn("authorization_code", rows[0])
            with database.connect() as db:
                account_id = db.execute("SELECT id FROM email_accounts").fetchone()[0]
                db.execute("INSERT INTO email_seen(account_id,message_uid,processed_at) VALUES(?,?,datetime('now'))", (account_id, "message-1"))
                db.execute("INSERT OR IGNORE INTO email_seen(account_id,message_uid,processed_at) VALUES(?,?,datetime('now'))", (account_id, "message-1"))
                count = db.execute("SELECT COUNT(*) FROM email_seen").fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
