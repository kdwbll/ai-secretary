from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Any, Optional

from .database import Database
from .safety import ApprovalService


class UsefulActionService:
    """Deterministic local calendar and mail-draft actions for v0.15."""

    def __init__(self, database: Database, safety: ApprovalService):
        self.database = database
        self.safety = safety

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError as exc:
            raise ValueError("日程时间格式无效") from exc

    def calendar_conflicts(self, start_at: str, end_at: str) -> list[dict[str, Any]]:
        start, end = self._time(start_at), self._time(end_at)
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        conflicts = []
        for row in self.database.rows("SELECT id,title,start_at,end_at,location,'local' AS source FROM local_calendar_events ORDER BY start_at"):
            try:
                other_start, other_end = self._time(row["start_at"]), self._time(row["end_at"])
            except ValueError:
                continue
            if other_start < end and other_end > start:
                conflicts.append(row)
        for row in self.database.rows("SELECT id,payload FROM events WHERE source='calendar' ORDER BY id DESC LIMIT 1000"):
            try:
                payload = json.loads(row["payload"] or "{}")
                other_start = self._time(str(payload.get("start_at") or ""))
                other_end = self._time(str(payload.get("end_at") or ""))
            except (ValueError, TypeError):
                continue
            if other_start < end and other_end > start:
                conflicts.append({"id": row["id"], "title": payload.get("title") or "已有日程", "start_at": other_start.isoformat(),
                                  "end_at": other_end.isoformat(), "location": payload.get("location") or "", "source": "android"})
        return conflicts

    def suggest_calendar(self, payload: dict[str, Any], *, goal_id: Optional[int] = None, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        start_at, end_at = str(payload.get("start_at") or ""), str(payload.get("end_at") or "")
        if not title:
            raise ValueError("日程标题不能为空")
        conflicts = self.calendar_conflicts(start_at, end_at)
        exact = {
            "title": title, "start_at": start_at, "end_at": end_at,
            "all_day": bool(payload.get("all_day", False)), "location": str(payload.get("location") or "").strip(),
            "notes": str(payload.get("notes") or "").strip(), "conflicts": conflicts,
        }
        if not idempotency_key:
            fingerprint = json.dumps({"goal_id": goal_id, **exact}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            idempotency_key = "calendar-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        return self.safety.request(
            "calendar.local_create", "write", f"创建本机日程：{title}", connector="calendar", goal_id=goal_id,
            target=f"{start_at} — {end_at}", exact_payload=exact, expires_minutes=60,
            idempotency_key=idempotency_key,
        )

    def execute_calendar(self, approval_id: int) -> dict[str, Any]:
        approval = self.safety.claim(approval_id, action_type="calendar.local_create", connector="calendar", actor="calendar-service")
        payload = approval["exact_payload"]
        self.calendar_conflicts(str(payload.get("start_at") or ""), str(payload.get("end_at") or ""))
        now = self._now()
        try:
            with self.database.connect() as db:
                cursor = db.execute(
                    "INSERT INTO local_calendar_events(goal_id,title,start_at,end_at,all_day,location,notes,source,approval_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (approval.get("goal_id"), str(payload.get("title") or "").strip(), payload["start_at"], payload["end_at"],
                     int(bool(payload.get("all_day"))), str(payload.get("location") or ""), str(payload.get("notes") or ""),
                     "approved_suggestion", approval_id, now, now),
                )
                event_id = int(cursor.lastrowid)
            result = {"id": event_id, "title": payload["title"], "start_at": payload["start_at"], "end_at": payload["end_at"]}
            self.safety.finish(approval_id, success=True, result=result, actor="calendar-service")
            return result
        except Exception as exc:
            self.safety.finish(approval_id, success=False, error=str(exc), actor="calendar-service")
            raise

    def calendar_events(self) -> list[dict[str, Any]]:
        rows = self.database.rows("SELECT * FROM local_calendar_events ORDER BY start_at,id")
        for row in rows:
            row["all_day"] = bool(row["all_day"])
        return rows

    def create_draft(self, *, recipients: list[str], cc: list[str], subject: str, body: str,
                     goal_id: Optional[int] = None, account_id: Optional[int] = None, source: str = "manual") -> dict[str, Any]:
        recipients = [item.strip() for item in recipients if item.strip()]
        if not recipients:
            raise ValueError("邮件草稿至少需要一个收件人")
        if not subject.strip() and not body.strip():
            raise ValueError("邮件主题和正文不能同时为空")
        now = self._now()
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO email_drafts(goal_id,account_id,recipients,cc,subject,body,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (goal_id, account_id, json.dumps(recipients, ensure_ascii=False), json.dumps([item.strip() for item in cc if item.strip()], ensure_ascii=False),
                 subject.strip(), body.strip(), source.strip() or "manual", now, now),
            )
            return self._draft(dict(db.execute("SELECT * FROM email_drafts WHERE id=?", (cursor.lastrowid,)).fetchone()))

    @staticmethod
    def _draft(item: dict[str, Any]) -> dict[str, Any]:
        item["recipients"] = json.loads(item["recipients"] or "[]")
        item["cc"] = json.loads(item["cc"] or "[]")
        return item

    def drafts(self) -> list[dict[str, Any]]:
        return [self._draft(row) for row in self.database.rows("SELECT * FROM email_drafts ORDER BY updated_at DESC,id DESC")]

    def update_draft(self, draft_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"recipients", "cc", "subject", "body"}
        changed = {key: value for key, value in fields.items() if key in allowed}
        if not changed:
            rows = self.database.rows("SELECT * FROM email_drafts WHERE id=?", (draft_id,))
            if not rows:
                raise KeyError("邮件草稿不存在")
            return self._draft(rows[0])
        for key in ("recipients", "cc"):
            if key in changed:
                changed[key] = json.dumps([str(item).strip() for item in changed[key] if str(item).strip()], ensure_ascii=False)
        for key in ("subject", "body"):
            if key in changed:
                changed[key] = str(changed[key]).strip()
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM email_drafts WHERE id=?", (draft_id,)).fetchone():
                raise KeyError("邮件草稿不存在")
            assignments = ",".join(f"{key}=?" for key in changed)
            db.execute(f"UPDATE email_drafts SET {assignments},updated_at=? WHERE id=?", (*changed.values(), self._now(), draft_id))
            return self._draft(dict(db.execute("SELECT * FROM email_drafts WHERE id=?", (draft_id,)).fetchone()))

    def delete_draft(self, draft_id: int) -> None:
        with self.database.connect() as db:
            cursor = db.execute("DELETE FROM email_drafts WHERE id=?", (draft_id,))
            if cursor.rowcount != 1:
                raise KeyError("邮件草稿不存在")
