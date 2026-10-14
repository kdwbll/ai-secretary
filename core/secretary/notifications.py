from __future__ import annotations

import platform
import subprocess
from datetime import datetime

from .database import Database


class NotificationService:
    def __init__(self, database: Database):
        self.database = database

    def publish(self, kind: str, title: str, body: str) -> int:
        full_body = body.strip()[:20_000]
        message = " ".join(full_body.replace("#", "").split())[:300]
        should_alert = self._may_alert(kind)
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO notifications(created_at,kind,title,body) VALUES(?,?,?,?)",
                (datetime.now().astimezone().isoformat(timespec="seconds"), kind, title[:80], full_body),
            )
            notification_id = int(cursor.lastrowid)
        if should_alert and platform.system() == "Darwin":
            script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
            try:
                subprocess.Popen(
                    ["osascript", "-e", script, title[:80], message],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass
        return notification_id

    def _may_alert(self, kind: str) -> bool:
        if self.database.setting("notifications_enabled", "0") != "1":
            return False
        quiet_start = self.database.setting("quiet_start", "22:30") or "22:30"
        quiet_end = self.database.setting("quiet_end", "07:30") or "07:30"
        now = datetime.now().astimezone().strftime("%H:%M")
        quiet = quiet_start <= now < quiet_end if quiet_start < quiet_end else now >= quiet_start or now < quiet_end
        if quiet and kind not in {"task_blocked", "approval_required"}:
            return False
        minutes = int(self.database.setting("notification_dedup_minutes", "60") or 60)
        rows = self.database.rows("SELECT id FROM notifications WHERE kind=? AND created_at>=datetime('now',?) ORDER BY id DESC LIMIT 1", (kind, f"-{max(1,min(minutes,1440))} minutes"))
        return not rows

    def since(self, after_id: int = 0, limit: int = 50) -> list[dict]:
        return self.database.rows(
            "SELECT id,created_at,kind,title,body FROM notifications WHERE id>? ORDER BY id LIMIT ?",
            (max(0, after_id), max(1, min(limit, 100))),
        )
