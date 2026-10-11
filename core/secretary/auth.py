from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .database import Database


@dataclass
class PairingCode:
    value: str
    expires_at: datetime
    attempts_left: int = 10


class AccessControl:
    """Issues revocable device tokens while persisting only their SHA-256 hashes."""

    def __init__(self, database: Database, code_lifetime_seconds: int = 300):
        self.database = database
        self.code_lifetime_seconds = code_lifetime_seconds
        self._pairing: Optional[PairingCode] = None
        self._last_seen_updates: dict[int, datetime] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_loopback(host: Optional[str]) -> bool:
        normalized = (host or "").split("%", 1)[0]
        return normalized in {"127.0.0.1", "::1", "localhost"}

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_pairing_code(self) -> dict:
        now = datetime.now().astimezone()
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock:
            self._pairing = PairingCode(code, now + timedelta(seconds=self.code_lifetime_seconds))
        return {"code": code, "expires_at": self._pairing.expires_at.isoformat(timespec="seconds"), "expires_in": self.code_lifetime_seconds}

    def pair(self, code: str, device_name: str) -> dict:
        now = datetime.now().astimezone()
        with self._lock:
            pending = self._pairing
            if pending is None or now >= pending.expires_at:
                self._pairing = None
                raise ValueError("配对码已失效，请在电脑端重新生成")
            if not hmac.compare_digest(pending.value, code.strip()):
                pending.attempts_left -= 1
                if pending.attempts_left <= 0:
                    self._pairing = None
                raise ValueError("配对码不正确")
            self._pairing = None

        name = device_name.strip()[:80] or "未命名设备"
        token = "sb_" + secrets.token_urlsafe(32)
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO access_tokens(name,token_hash,created_at) VALUES(?,?,?)",
                (name, self.token_hash(token), now.isoformat(timespec="seconds")),
            )
            token_id = int(cursor.lastrowid)
        return {"id": token_id, "name": name, "token": token}

    def verify(self, token: Optional[str]) -> bool:
        if not token or not token.startswith("sb_"):
            return False
        digest = self.token_hash(token)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.connect() as db:
            row = db.execute(
                "SELECT id FROM access_tokens WHERE token_hash=? AND revoked_at IS NULL",
                (digest,),
            ).fetchone()
            if not row:
                return False
            token_id = int(row[0])
            with self._lock:
                previous = self._last_seen_updates.get(token_id)
                should_update = previous is None or datetime.now().astimezone() - previous >= timedelta(minutes=1)
                if should_update:
                    self._last_seen_updates[token_id] = datetime.now().astimezone()
            if should_update:
                db.execute("UPDATE access_tokens SET last_used_at=? WHERE id=?", (now, token_id))
        return True

    def devices(self) -> list[dict]:
        return self.database.rows(
            "SELECT id,name,created_at,last_used_at FROM access_tokens "
            "WHERE revoked_at IS NULL ORDER BY id DESC"
        )

    def revoke(self, token_id: int) -> bool:
        with self._lock:
            self._last_seen_updates.pop(token_id, None)
        with self.database.connect() as db:
            cursor = db.execute(
                "UPDATE access_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now().astimezone().isoformat(timespec="seconds"), token_id),
            )
            return cursor.rowcount > 0
