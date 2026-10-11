from __future__ import annotations

import platform
import subprocess
from datetime import datetime

from .database import Database


class NotificationService:
    def __init__(self, database: Database):
        self.database = database

    def publish(self, kind: str, title: str, body: str) -> int:
        message = " ".join(body.replace("#", "").split())[:300]
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO notifications(created_at,kind,title,body) VALUES(?,?,?,?)",
                (datetime.now().astimezone().isoformat(timespec="seconds"), kind, title[:80], message),
            )
            notification_id = int(cursor.lastrowid)
        if self.database.setting("notifications_enabled", "0") == "1" and platform.system() == "Darwin":
            script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
            try:
                subprocess.Popen(
                    ["osascript", "-e", script, title[:80], message],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass
        return notification_id

    def since(self, after_id: int = 0, limit: int = 50) -> list[dict]:
        return self.database.rows(
            "SELECT id,created_at,kind,title,body FROM notifications WHERE id>? ORDER BY id LIMIT ?",
            (max(0, after_id), max(1, min(limit, 100))),
        )
