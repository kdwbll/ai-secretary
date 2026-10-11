import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.database import Database, LATEST_SCHEMA_VERSION, Migration


class DatabaseMigrationTests(TestCase):
    def test_fresh_database_records_every_migration(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            with database.connect() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                history = db.execute("SELECT version,name FROM schema_migrations ORDER BY version").fetchall()

            self.assertEqual(version, LATEST_SCHEMA_VERSION)
            self.assertEqual([row[0] for row in history], [1, 2, 3])

    def test_legacy_database_upgrades_without_losing_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, base_url TEXT NOT NULL, api_key TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '[]', kind TEXT NOT NULL DEFAULT 'openai')")
                db.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_message TEXT NOT NULL, assistant_message TEXT NOT NULL DEFAULT '', sources TEXT NOT NULL DEFAULT '[]', provider TEXT, model TEXT)")
                db.execute("INSERT INTO providers(name,base_url) VALUES('旧供应商','http://localhost')")
                db.execute("INSERT INTO chat_messages(created_at,user_message) VALUES('2026-10-11','旧对话')")

            database = Database(path)
            provider = database.rows("SELECT name,consumption_level FROM providers")[0]
            chat = database.rows("SELECT user_message,attachments FROM chat_messages")[0]

            self.assertEqual(provider, {"name": "旧供应商", "consumption_level": "medium"})
            self.assertEqual(chat, {"user_message": "旧对话", "attachments": "{}"})

    def test_failed_migration_rolls_back_and_does_not_advance_version(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
                db.execute("CREATE TABLE marker (value TEXT)")

                def first(connection):
                    connection.execute("INSERT INTO marker(value) VALUES('kept')")

                def failing(connection):
                    connection.execute("INSERT INTO marker(value) VALUES('rolled back')")
                    raise ValueError("boom")

                migrations = (Migration(1, "first", first), Migration(2, "failing", failing))
                with self.assertRaisesRegex(RuntimeError, "已回滚"):
                    Database._run_migrations(db, migrations)

                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT value FROM marker").fetchall(), [("kept",)])
                self.assertEqual(db.execute("SELECT version FROM schema_migrations").fetchall(), [(1,)])

    def test_migration_registry_rejects_version_gaps(self):
        with sqlite3.connect(":memory:") as db:
            with self.assertRaisesRegex(RuntimeError, "连续递增"):
                Database._run_migrations(db, (Migration(2, "gap", lambda connection: None),))

    def test_connection_context_rolls_back_on_error(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            with self.assertRaisesRegex(ValueError, "stop"):
                with database.connect() as db:
                    db.execute("INSERT INTO settings(key,value) VALUES('temporary','value')")
                    raise ValueError("stop")
            self.assertEqual(database.rows("SELECT key FROM settings WHERE key='temporary'"), [])

    def test_newer_database_is_rejected_before_schema_changes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "future.db"
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=999")
            with self.assertRaisesRegex(RuntimeError, "请升级程序"):
                Database(path)
            with sqlite3.connect(path) as db:
                tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [])
