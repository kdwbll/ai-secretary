from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.secretary.database import Database
from core.secretary.models import ModelRouter, Route


class RouterTests(unittest.TestCase):
    def test_model_price_recalculates_existing_calls_in_cny(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("priced", "https://example.com/v1", "key", ["model"])
            with database.connect() as db:
                db.execute(
                    "INSERT INTO ai_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,status) VALUES(datetime('now'),'smart','priced','model',1000000,500000,'ok')"
                )
            router.save_price("priced", "model", 2.0, 6.0, "CNY")
            cost = database.rows("SELECT estimated_cost FROM ai_calls")[0]["estimated_cost"]
            self.assertAlmostEqual(cost, 5.0)

    def test_usd_price_uses_configured_exchange_rate(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("usd", "https://example.com/v1", "key", ["model"])
            router.set_usd_cny_rate(7.0)
            router.save_price("usd", "model", 1.0, 2.0, "USD")
            self.assertAlmostEqual(router._cost_cny("usd", "model", 1_000_000, 1_000_000), 21.0)

    def test_known_models_receive_editable_default_prices(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("DeepSeek", "https://api.deepseek.com/v1", "key", ["deepseek-flash"])
            provider = router.providers()[0]
            self.assertEqual(provider["prices"]["deepseek-flash"]["currency"], "USD")
            self.assertEqual(provider["prices"]["deepseek-flash"]["output_per_million"], 1.2)

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
            self.assertNotEqual(secret, "kept-secret")
            self.assertTrue(secret.startswith("enc:v1:"))
            self.assertEqual(router.secrets.decrypt(secret), "kept-secret")

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

    def test_empty_model_content_is_an_error(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("empty", "https://example.com/v1", "key", ["model"])
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":null}}]}'
            with patch("urllib.request.urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "空内容"):
                    router._openai_call("smart", "empty", "model", [], 0.2)

    def test_length_finish_reason_continues_for_medium_provider(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("medium", "https://example.com/v1", "key", ["model"], consumption_level="medium")
            first = unittest.mock.MagicMock()
            first.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"first"},"finish_reason":"length"}],"usage":{"completion_tokens":4096}}'
            second = unittest.mock.MagicMock()
            second.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"second"},"finish_reason":"stop"}],"usage":{"completion_tokens":20}}'
            with patch("urllib.request.urlopen", side_effect=[first, second]):
                answer = router._openai_call("smart", "medium", "model", [{"role": "user", "content": "question"}], 0.2)
            self.assertEqual(answer, "first\n\nsecond")

    def test_openai_input_output_token_aliases_are_recorded(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("alias", "https://example.com/v1", "key", ["model"])
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"done"},"finish_reason":"stop"}],"usage":{"input_tokens":123,"output_tokens":45}}'
            with patch("urllib.request.urlopen", return_value=response):
                router._openai_call("smart", "alias", "model", [{"role": "user", "content": "question"}], 0.2)
            call = database.rows("SELECT prompt_tokens,completion_tokens FROM ai_calls")[0]
            self.assertEqual((call["prompt_tokens"], call["completion_tokens"]), (123, 45))

    def test_missing_usage_is_estimated_locally(self):
        with TemporaryDirectory() as temp:
            database = Database(Path(temp) / "db.sqlite")
            router = ModelRouter(database)
            router.save_provider("estimate", "https://example.com/v1", "key", ["model"])
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"estimated answer"},"finish_reason":"stop"}]}'
            with patch("urllib.request.urlopen", return_value=response):
                router._openai_call("smart", "estimate", "model", [{"role": "user", "content": "estimate this question"}], 0.2)
            call = database.rows("SELECT prompt_tokens,completion_tokens FROM ai_calls")[0]
            self.assertGreater(call["prompt_tokens"], 0)
            self.assertGreater(call["completion_tokens"], 0)

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
