from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from .database import Database


ACTION_LEVELS = {"read", "draft", "write", "irreversible"}
FINAL_STATUSES = {"denied", "expired", "revoked", "executed", "failed"}


class ApprovalError(ValueError):
    pass


class ApprovalService:
    """Central policy, durable approvals, connector grants, and chained audit."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        for key in ("exact_payload", "result", "details", "scopes"):
            if key in item and isinstance(item[key], str):
                try:
                    item[key] = json.loads(item[key] or ("[]" if key == "scopes" else "{}"))
                except json.JSONDecodeError:
                    item[key] = [] if key == "scopes" else {}
        if "enabled" in item:
            item["enabled"] = bool(item["enabled"])
        return item

    def _audit(
        self,
        db: sqlite3.Connection,
        event_type: str,
        *,
        action_id: Optional[int] = None,
        goal_id: Optional[int] = None,
        connector: str = "",
        actor: str = "system",
        details: Optional[dict[str, Any]] = None,
    ) -> int:
        now = self._now().isoformat(timespec="seconds")
        previous = db.execute("SELECT event_hash FROM action_audit ORDER BY id DESC LIMIT 1").fetchone()
        previous_hash = str(previous[0]) if previous else ""
        body = self._json({
            "created_at": now, "event_type": event_type, "action_id": action_id,
            "goal_id": goal_id, "connector": connector, "actor": actor,
            "details": details or {}, "previous_hash": previous_hash,
        })
        event_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        cursor = db.execute(
            "INSERT INTO action_audit(created_at,event_type,action_id,goal_id,connector,actor,details,previous_hash,event_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (now, event_type, action_id, goal_id, connector, actor, self._json(details or {}), previous_hash, event_hash),
        )
        return int(cursor.lastrowid)

    def request(
        self,
        action_type: str,
        level: str,
        summary: str,
        *,
        connector: str = "",
        goal_id: Optional[int] = None,
        target: str = "",
        exact_payload: Optional[dict[str, Any]] = None,
        expires_minutes: int = 30,
        idempotency_key: Optional[str] = None,
        actor: str = "assistant",
    ) -> dict[str, Any]:
        if level not in ACTION_LEVELS:
            raise ApprovalError("动作等级无效")
        if not action_type.strip() or not summary.strip():
            raise ApprovalError("动作类型和摘要不能为空")
        if not 1 <= expires_minutes <= 1440:
            raise ApprovalError("审批有效期必须在 1 到 1440 分钟之间")
        key = (idempotency_key or f"approval_{secrets.token_urlsafe(18)}").strip()
        now = self._now()
        expires = now + timedelta(minutes=expires_minutes)
        with self.database.connect() as db:
            existing = db.execute("SELECT * FROM action_approvals WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return self._decode(existing)
            cursor = db.execute(
                "INSERT INTO action_approvals(idempotency_key,action_type,level,connector,goal_id,summary,target,exact_payload,status,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (key, action_type.strip(), level, connector.strip(), goal_id, summary.strip(), target.strip(),
                 self._json(exact_payload or {}), "pending", now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
            )
            action_id = int(cursor.lastrowid)
            self._audit(db, "approval.requested", action_id=action_id, goal_id=goal_id, connector=connector, actor=actor,
                        details={"level": level, "summary": summary.strip(), "target": target.strip()})
            return self._decode(db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone())

    def _expire(self, db: sqlite3.Connection, action_id: Optional[int] = None) -> None:
        now = self._now().isoformat(timespec="seconds")
        params: tuple[Any, ...] = (now,) if action_id is None else (now, action_id)
        suffix = "" if action_id is None else " AND id=?"
        rows = db.execute(
            f"SELECT id,goal_id,connector FROM action_approvals WHERE status='pending' AND expires_at<=?{suffix}", params
        ).fetchall()
        for row in rows:
            db.execute("UPDATE action_approvals SET status='expired',decided_at=?,decided_by='system' WHERE id=?", (now, row["id"]))
            self._audit(db, "approval.expired", action_id=row["id"], goal_id=row["goal_id"], connector=row["connector"])

    def list(self, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as db:
            self._expire(db)
            params: list[Any] = []
            where = ""
            if status:
                where = " WHERE status=?"
                params.append(status)
            params.append(max(1, min(limit, 500)))
            rows = db.execute(f"SELECT * FROM action_approvals{where} ORDER BY id DESC LIMIT ?", tuple(params)).fetchall()
            return [self._decode(row) for row in rows]

    def get(self, action_id: int) -> dict[str, Any]:
        with self.database.connect() as db:
            self._expire(db, action_id)
            row = db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise KeyError("审批不存在")
            return self._decode(row)

    def decide(self, action_id: int, decision: str, *, edited_payload: Optional[dict[str, Any]] = None, actor: str = "user") -> dict[str, Any]:
        if decision not in {"approve", "deny", "revoke"}:
            raise ApprovalError("审批决定无效")
        with self.database.connect() as db:
            self._expire(db, action_id)
            row = db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise KeyError("审批不存在")
            status = str(row["status"])
            if decision == "revoke":
                if status not in {"pending", "approved"}:
                    raise ApprovalError("只有待处理或尚未执行的审批可以撤销")
                next_status = "revoked"
            else:
                if status != "pending":
                    raise ApprovalError("这条审批已处理，不能重复提交")
                next_status = "approved" if decision == "approve" else "denied"
            payload = self._json(edited_payload) if edited_payload is not None else row["exact_payload"]
            now = self._now().isoformat(timespec="seconds")
            db.execute(
                "UPDATE action_approvals SET status=?,exact_payload=?,decided_at=?,decided_by=? WHERE id=?",
                (next_status, payload, now, actor, action_id),
            )
            self._audit(db, f"approval.{next_status}", action_id=action_id, goal_id=row["goal_id"], connector=row["connector"], actor=actor,
                        details={"edited": edited_payload is not None})
            return self._decode(db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone())

    def claim(self, action_id: int, *, action_type: str, connector: str = "", actor: str = "executor") -> dict[str, Any]:
        """Atomically consume an approval before a write or irreversible action."""
        with self.database.connect() as db:
            self._expire(db, action_id)
            now = self._now().isoformat(timespec="seconds")
            cursor = db.execute(
                "UPDATE action_approvals SET status='executing',executed_at=? "
                "WHERE id=? AND status='approved' AND action_type=? AND connector=? AND expires_at>?",
                (now, action_id, action_type, connector, now),
            )
            if cursor.rowcount != 1:
                raise ApprovalError("缺少有效审批，动作已阻止")
            row = db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone()
            self._audit(db, "action.executing", action_id=action_id, goal_id=row["goal_id"], connector=connector, actor=actor)
            return self._decode(row)

    def finish(self, action_id: int, *, success: bool, result: Optional[dict[str, Any]] = None, error: str = "", actor: str = "executor") -> dict[str, Any]:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone()
            if not row:
                raise KeyError("审批不存在")
            if row["status"] != "executing":
                raise ApprovalError("动作未处于执行中")
            status = "executed" if success else "failed"
            db.execute("UPDATE action_approvals SET status=?,result=?,error=? WHERE id=?", (status, self._json(result or {}), error, action_id))
            self._audit(db, f"action.{status}", action_id=action_id, goal_id=row["goal_id"], connector=row["connector"], actor=actor,
                        details={"result": result or {}, "error": error})
            return self._decode(db.execute("SELECT * FROM action_approvals WHERE id=?", (action_id,)).fetchone())

    def require(self, level: str, *, connector: str = "", approval_id: Optional[int] = None, action_type: str = "") -> Optional[dict[str, Any]]:
        if level not in ACTION_LEVELS:
            raise ApprovalError("动作等级无效")
        if connector and not self.connector_enabled(connector):
            raise ApprovalError("连接器权限已撤销")
        if level in {"read", "draft"}:
            if connector:
                self.touch_connector(connector)
            return None
        if approval_id is None:
            raise ApprovalError("写入或不可逆动作必须先获得审批")
        return self.claim(approval_id, action_type=action_type, connector=connector)

    def connectors(self) -> list[dict[str, Any]]:
        return [self._decode(row) for row in self.database.rows("SELECT * FROM connector_permissions ORDER BY display_name")]

    def connector_enabled(self, connector: str) -> bool:
        rows = self.database.rows("SELECT enabled FROM connector_permissions WHERE connector=?", (connector,))
        return bool(rows and rows[0]["enabled"])

    def touch_connector(self, connector: str) -> None:
        with self.database.connect() as db:
            now = self._now().isoformat(timespec="seconds")
            db.execute("UPDATE connector_permissions SET last_used_at=?,updated_at=? WHERE connector=? AND enabled=1", (now, now, connector))

    def set_connector(self, connector: str, enabled: bool, actor: str = "user") -> dict[str, Any]:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM connector_permissions WHERE connector=?", (connector,)).fetchone()
            if not row:
                raise KeyError("连接器不存在")
            now = self._now().isoformat(timespec="seconds")
            revoked_at = None if enabled else now
            db.execute("UPDATE connector_permissions SET enabled=?,revoked_at=?,updated_at=? WHERE connector=?", (int(enabled), revoked_at, now, connector))
            if not enabled:
                db.execute(
                    "UPDATE tasks SET enabled=0,updated_at=? WHERE schedule='event' AND event_source=? AND enabled=1",
                    (now, connector),
                )
                pending = db.execute(
                    "SELECT id,goal_id FROM action_approvals WHERE connector=? AND status IN ('pending','approved')", (connector,)
                ).fetchall()
                for item in pending:
                    db.execute("UPDATE action_approvals SET status='revoked',decided_at=?,decided_by=? WHERE id=?", (now, actor, item["id"]))
            self._audit(db, "connector.enabled" if enabled else "connector.revoked", connector=connector, actor=actor)
            return self._decode(db.execute("SELECT * FROM connector_permissions WHERE connector=?", (connector,)).fetchone())

    def audit(self, *, goal_id: Optional[int] = None, connector: str = "", date_from: str = "", date_to: str = "", limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if goal_id is not None:
            clauses.append("goal_id=?")
            params.append(goal_id)
        if connector:
            clauses.append("connector=?")
            params.append(connector)
        if date_from:
            clauses.append("created_at>=?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at<=?")
            params.append(date_to)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        return [self._decode(row) for row in self.database.rows(f"SELECT * FROM action_audit{where} ORDER BY id DESC LIMIT ?", tuple(params))]

    def verify_audit_chain(self) -> dict[str, Any]:
        rows = self.database.rows("SELECT * FROM action_audit ORDER BY id")
        previous = ""
        for row in rows:
            details = json.loads(row["details"] or "{}")
            body = self._json({
                "created_at": row["created_at"], "event_type": row["event_type"], "action_id": row["action_id"],
                "goal_id": row["goal_id"], "connector": row["connector"], "actor": row["actor"],
                "details": details, "previous_hash": previous,
            })
            expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous or row["event_hash"] != expected:
                return {"valid": False, "entries": len(rows), "broken_at": row["id"]}
            previous = row["event_hash"]
        return {"valid": True, "entries": len(rows), "head": previous}
