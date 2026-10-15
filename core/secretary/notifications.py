from __future__ import annotations

import platform
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .database import Database


class NotificationService:
    def __init__(self, database: Database):
        self.database = database

    def publish(self, kind: str, title: str, body: str, reason_key: str = "") -> int:
        full_body = body.strip()[:20_000]
        message = " ".join(full_body.replace("#", "").split())[:300]
        reason_key = reason_key.strip()[:200]
        should_alert = self._may_alert(kind, reason_key)
        now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO notifications(created_at,kind,title,body,reason_key,alerted) VALUES(?,?,?,?,?,?)",
                (now, kind, title[:80], full_body, reason_key, int(should_alert)),
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

    def _may_alert(self, kind: str, reason_key: str = "") -> bool:
        if self.database.setting("notifications_enabled", "0") != "1":
            return False
        quiet_start = self.database.setting("quiet_start", "22:30") or "22:30"
        quiet_end = self.database.setting("quiet_end", "07:30") or "07:30"
        current = datetime.now(ZoneInfo("Asia/Shanghai"))
        now = current.strftime("%H:%M")
        quiet = quiet_start <= now < quiet_end if quiet_start < quiet_end else now >= quiet_start or now < quiet_end
        if quiet and kind not in {"task_blocked", "approval_required"}:
            return False
        if reason_key:
            cutoff = (current - timedelta(hours=24)).isoformat(timespec="seconds")
            if self.database.rows(
                "SELECT id FROM notifications WHERE alerted=1 AND reason_key=? AND created_at>=? LIMIT 1",
                (reason_key, cutoff),
            ):
                return False
        start = current.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        limit = max(1, min(int(self.database.setting("notification_daily_limit", "3") or 3), 20))
        count = self.database.rows(
            "SELECT COUNT(*) AS count FROM notifications WHERE alerted=1 AND created_at>=?",
            (start,),
        )[0]["count"]
        if int(count) >= limit:
            return False
        minutes = int(self.database.setting("notification_dedup_minutes", "60") or 60)
        cutoff = (current - timedelta(minutes=max(1, min(minutes, 1440)))).isoformat(timespec="seconds")
        rows = self.database.rows(
            "SELECT id FROM notifications WHERE alerted=1 AND kind=? AND created_at>=? ORDER BY id DESC LIMIT 1",
            (kind, cutoff),
        )
        return not rows

    def since(self, after_id: int = 0, limit: int = 50) -> list[dict]:
        return self.database.rows(
            "SELECT id,created_at,kind,title,body,reason_key,alerted FROM notifications WHERE id>? ORDER BY id LIMIT ?",
            (max(0, after_id), max(1, min(limit, 100))),
        )
