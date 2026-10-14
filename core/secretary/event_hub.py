from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .database import Database


class EventHub:
    """Idempotent local event intake used by connectors and scheduled work."""
    def __init__(self, database: Database): self.database = database
    def publish(self, source: str, kind: str, payload: dict[str, Any], trust: str = "untrusted") -> dict[str, Any]:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(f"{source}:{kind}:{canonical}".encode()).hexdigest()
        with self.database.connect() as db:
            prior = db.execute("SELECT event_id FROM event_receipts WHERE fingerprint=?", (fingerprint,)).fetchone()
            if prior: return {"id": int(prior["event_id"]), "duplicate": True}
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            event = db.execute("INSERT INTO events(created_at,source,kind,payload,status) VALUES(?,?,?,?,?)", (now,source,kind,json.dumps({**payload,"trust":trust},ensure_ascii=False),"pending"))
            db.execute("INSERT INTO event_receipts(fingerprint,event_id,created_at) VALUES(?,?,?)", (fingerprint,event.lastrowid,now))
            return {"id": int(event.lastrowid), "duplicate": False}
