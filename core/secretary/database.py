from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS providers (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, base_url TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '[]', kind TEXT NOT NULL DEFAULT 'openai',
  consumption_level TEXT NOT NULL DEFAULT 'medium'
);
CREATE TABLE IF NOT EXISTS model_routes (
  task TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
  fallback_provider TEXT, fallback_model TEXT
);
CREATE TABLE IF NOT EXISTS ai_calls (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, task TEXT NOT NULL, provider TEXT,
  model TEXT, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
  estimated_cost REAL DEFAULT 0, status TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS model_prices (
  provider TEXT NOT NULL, model TEXT NOT NULL,
  input_per_million REAL NOT NULL DEFAULT 0,
  output_per_million REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'CNY', updated_at TEXT NOT NULL,
  PRIMARY KEY(provider, model)
);
CREATE TABLE IF NOT EXISTS mutations (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
  before_text TEXT NOT NULL, after_text TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  hash TEXT PRIMARY KEY, original_name TEXT NOT NULL, stored_path TEXT NOT NULL,
  created_at TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS email_accounts (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL DEFAULT 993,
  username TEXT UNIQUE NOT NULL, authorization_code TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  last_sync TEXT
);
CREATE TABLE IF NOT EXISTS email_seen (
  account_id INTEGER NOT NULL, message_uid TEXT NOT NULL, processed_at TEXT NOT NULL,
  PRIMARY KEY(account_id, message_uid)
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_message TEXT NOT NULL,
  assistant_message TEXT NOT NULL DEFAULT '', sources TEXT NOT NULL DEFAULT '[]',
  provider TEXT, model TEXT, attachments TEXT NOT NULL DEFAULT '{}', title TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, label TEXT NOT NULL DEFAULT '',
  latitude REAL, longitude REAL, enabled INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_samples (
  id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, metric TEXT NOT NULL,
  value REAL NOT NULL, unit TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
  external_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_health_metric_time ON health_samples(metric, recorded_at);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_tokens (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _add_provider_consumption_level(db: sqlite3.Connection) -> None:
    if "consumption_level" not in _columns(db, "providers"):
        db.execute("ALTER TABLE providers ADD COLUMN consumption_level TEXT NOT NULL DEFAULT 'medium'")


def _add_chat_attachments(db: sqlite3.Connection) -> None:
    if "attachments" not in _columns(db, "chat_messages"):
        db.execute("ALTER TABLE chat_messages ADD COLUMN attachments TEXT NOT NULL DEFAULT '{}'")


def _add_access_tokens(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS access_tokens ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, "
        "created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT)"
    )


def _add_chat_titles(db: sqlite3.Connection) -> None:
    if "title" not in _columns(db, "chat_messages"):
        db.execute("ALTER TABLE chat_messages ADD COLUMN title TEXT NOT NULL DEFAULT ''")
    db.execute("UPDATE chat_messages SET title=substr(trim(user_message),1,40) WHERE title='' OR title IS NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at)")


def _add_locations(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS locations ("
        "id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, label TEXT NOT NULL DEFAULT '', "
        "latitude REAL, longitude REAL, enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)"
    )


def _add_notifications(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS notifications ("
        "id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, "
        "title TEXT NOT NULL, body TEXT NOT NULL)"
    )


def _switch_default_search_to_bocha(db: sqlite3.Connection) -> None:
    db.execute("UPDATE settings SET value='bocha' WHERE key='web_search_provider' AND value='brave'")


def _add_calendar_event_index(db: sqlite3.Connection) -> None:
    # Calendar instances are identified by the Android provider event id plus
    # their occurrence start.  Keep the key inside the existing event payload
    # so the timeline, reports, and device API retain one event model.
    db.execute("CREATE INDEX IF NOT EXISTS idx_events_source_status ON events(source, status, id DESC)")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "add provider consumption level", _add_provider_consumption_level),
    Migration(2, "add chat attachments", _add_chat_attachments),
    Migration(3, "add device access tokens", _add_access_tokens),
    Migration(4, "add chat titles and search", _add_chat_titles),
    Migration(5, "add local location sources", _add_locations),
    Migration(6, "add local notification outbox", _add_notifications),
    Migration(7, "switch default web search to bocha", _switch_default_search_to_bocha),
    Migration(8, "index collected calendar events", _add_calendar_event_index),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.path)) as db:
            db.row_factory = sqlite3.Row
            current = int(db.execute("PRAGMA user_version").fetchone()[0])
            if current > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {current} 高于当前程序支持的版本 {LATEST_SCHEMA_VERSION}，请升级程序"
                )
            db.executescript(SCHEMA)
            self._run_migrations(db)
            defaults = {
                "morning_time": "07:30", "review_time": "22:30", "max_context_files": "5",
                "usd_cny_rate": "7.20", "location_enabled": "0", "map_provider": "amap",
                "notifications_enabled": "0", "theme": "system", "max_upload_mb": "200",
            }
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

    @staticmethod
    def _run_migrations(db: sqlite3.Connection, migrations: Sequence[Migration] = MIGRATIONS) -> None:
        versions = [migration.version for migration in migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise RuntimeError("数据库迁移版本必须从 1 开始连续递增")
        current = int(db.execute("PRAGMA user_version").fetchone()[0])
        latest = versions[-1] if versions else 0
        if current > latest:
            raise RuntimeError(f"数据库版本 {current} 高于当前程序支持的版本 {latest}，请升级程序")
        for migration in migrations:
            if migration.version <= current:
                continue
            try:
                db.execute("BEGIN IMMEDIATE")
                migration.apply(db)
                db.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (migration.version, migration.name, datetime.now().astimezone().isoformat(timespec="seconds")),
                )
                db.execute(f"PRAGMA user_version={migration.version}")
                db.commit()
            except Exception as exc:
                db.rollback()
                raise RuntimeError(f"数据库迁移 {migration.version}（{migration.name}）失败，已回滚") from exc

        required = {
            "providers": {"consumption_level"},
            "chat_messages": {"attachments"},
            "access_tokens": {"name", "token_hash", "revoked_at"},
            "chat_messages": {"attachments", "title"},
            "locations": {"source", "latitude", "longitude", "enabled"},
            "notifications": {"kind", "title", "body"},
        }
        missing = [f"{table}.{column}" for table, columns in required.items() for column in columns - _columns(db, table)]
        if missing:
            raise RuntimeError("数据库结构校验失败，缺少字段：" + "、".join(missing))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path))
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def record_mutation(self, path: str, before: str, after: str, reason: str, actor: str = "AI") -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO mutations(created_at,path,before_text,after_text,reason,actor) VALUES(?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), path, before, after, reason, actor),
            )
            return int(cur.lastrowid)

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def add_event(self, source: str, kind: str, payload: dict[str, Any]) -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO events(created_at,source,kind,payload) VALUES(?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), source, kind, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cur.lastrowid)
