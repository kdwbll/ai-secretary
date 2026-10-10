from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS providers (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, base_url TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '[]', kind TEXT NOT NULL DEFAULT 'openai'
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
  provider TEXT, model TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            defaults = {"morning_time": "07:30", "review_time": "22:30", "max_context_files": "5"}
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path))
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
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
