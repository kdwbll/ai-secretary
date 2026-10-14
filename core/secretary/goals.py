from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from .database import Database


GOAL_STATUSES = ("active", "paused", "completed", "cancelled")
TASK_STATUSES = ("pending", "in_progress", "blocked", "completed", "cancelled")
GOAL_TRANSITIONS = {
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
TASK_TRANSITIONS = {
    "pending": {"in_progress", "blocked", "completed", "cancelled"},
    "in_progress": {"pending", "blocked", "completed", "cancelled"},
    "blocked": {"pending", "in_progress", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class GoalService:
    """Persistent goal/task model with validated state changes and audit events."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _clean_title(title: str, label: str) -> str:
        result = title.strip()
        if not result:
            raise ValueError(f"{label}不能为空")
        return result

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        item = dict(row)
        if "position" in item:
            item["position"] = int(item["position"])
        return item

    @staticmethod
    def _event(db, goal_id: int, task_id: Optional[int], kind: str, payload: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO task_events(goal_id,task_id,created_at,kind,payload) VALUES(?,?,?,?,?)",
            (goal_id, task_id, GoalService._now(), kind, json.dumps(payload, ensure_ascii=False)),
        )

    def list_goals(self, include_closed: bool = True) -> list[dict[str, Any]]:
        where = "" if include_closed else "WHERE g.status IN ('active','paused')"
        rows = self.database.rows(
            "SELECT g.*, COUNT(t.id) AS task_count, "
            "SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) AS completed_task_count "
            "FROM goals g LEFT JOIN tasks t ON t.goal_id=g.id " + where +
            " GROUP BY g.id ORDER BY CASE g.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, "
            "COALESCE(g.due_at,'9999-12-31') ASC, g.updated_at DESC, g.id DESC"
        )
        for row in rows:
            row["task_count"] = int(row["task_count"] or 0)
            row["completed_task_count"] = int(row["completed_task_count"] or 0)
            row["tasks"] = self.list_tasks(int(row["id"]))
        return rows

    def goal(self, goal_id: int) -> dict[str, Any]:
        rows = self.database.rows("SELECT * FROM goals WHERE id=?", (goal_id,))
        if not rows:
            raise KeyError("目标不存在")
        result = rows[0]
        result["tasks"] = self.list_tasks(goal_id)
        return result

    def create_goal(self, title: str, description: str = "", due_at: Optional[str] = None,
                    idempotency_key: Optional[str] = None) -> dict[str, Any]:
        title = self._clean_title(title, "目标标题")
        key = (idempotency_key or "").strip() or None
        with self.database.connect() as db:
            if key:
                previous = db.execute("SELECT * FROM goals WHERE idempotency_key=?", (key,)).fetchone()
                if previous:
                    return self._row(previous)
            now = self._now()
            cursor = db.execute(
                "INSERT INTO goals(title,description,status,due_at,created_at,updated_at,idempotency_key) VALUES(?,?,?,?,?,?,?)",
                (title, description.strip(), "active", due_at, now, now, key),
            )
            goal_id = int(cursor.lastrowid)
            self._event(db, goal_id, None, "goal.created", {"title": title, "due_at": due_at})
            return self._row(db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())

    def update_goal(self, goal_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "description", "due_at"}
        changed = {key: value for key, value in fields.items() if key in allowed}
        if not changed:
            return self.goal(goal_id)
        if "title" in changed:
            changed["title"] = self._clean_title(str(changed["title"]), "目标标题")
        if "description" in changed and changed["description"] is not None:
            changed["description"] = str(changed["description"]).strip()
        if "due_at" in changed and changed["due_at"] is not None:
            changed["due_at"] = str(changed["due_at"]).strip() or None
        with self.database.connect() as db:
            current = db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            if not current:
                raise KeyError("目标不存在")
            assignments = ",".join(f"{key}=?" for key in changed)
            db.execute(f"UPDATE goals SET {assignments},updated_at=? WHERE id=?", (*changed.values(), self._now(), goal_id))
            self._event(db, goal_id, None, "goal.updated", {"fields": changed})
            return self._row(db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())

    def set_goal_status(self, goal_id: int, status: str) -> dict[str, Any]:
        if status not in GOAL_STATUSES:
            raise ValueError("目标状态无效")
        with self.database.connect() as db:
            current = db.execute("SELECT status FROM goals WHERE id=?", (goal_id,)).fetchone()
            if not current:
                raise KeyError("目标不存在")
            previous = current["status"]
            if previous == status:
                return self._row(db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())
            if status not in GOAL_TRANSITIONS[previous]:
                raise ValueError(f"目标不能从 {previous} 变更为 {status}")
            now = self._now()
            completed_at = now if status == "completed" else None
            db.execute("UPDATE goals SET status=?,completed_at=?,updated_at=? WHERE id=?", (status, completed_at, now, goal_id))
            self._event(db, goal_id, None, "goal.status_changed", {"from": previous, "to": status})
            return self._row(db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())

    def list_tasks(self, goal_id: int) -> list[dict[str, Any]]:
        return self.database.rows(
            "SELECT * FROM tasks WHERE goal_id=? ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END, position, id",
            (goal_id,),
        )

    def create_task(self, goal_id: int, title: str, description: str = "", due_at: Optional[str] = None,
                    position: Optional[int] = None, idempotency_key: Optional[str] = None, schedule: str = "manual", next_run_at: Optional[str] = None, max_retries: int = 3, interval_minutes: int = 0) -> dict[str, Any]:
        title = self._clean_title(title, "任务标题")
        self._validate_schedule(schedule, next_run_at, max_retries, interval_minutes)
        key = (idempotency_key or "").strip() or None
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM goals WHERE id=?", (goal_id,)).fetchone():
                raise KeyError("目标不存在")
            if key:
                previous = db.execute("SELECT * FROM tasks WHERE goal_id=? AND idempotency_key=?", (goal_id, key)).fetchone()
                if previous:
                    return self._row(previous)
            if position is None:
                position = int(db.execute("SELECT COALESCE(MAX(position),0)+1 FROM tasks WHERE goal_id=?", (goal_id,)).fetchone()[0])
            now = self._now()
            cursor = db.execute(
                "INSERT INTO tasks(goal_id,title,description,status,due_at,position,created_at,updated_at,idempotency_key,schedule,next_run_at,max_retries,interval_minutes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (goal_id, title, description.strip(), "pending", due_at, position, now, now, key, schedule, next_run_at, max_retries, interval_minutes),
            )
            task_id = int(cursor.lastrowid)
            self._event(db, goal_id, task_id, "task.created", {"title": title, "due_at": due_at, "position": position})
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def update_task(self, task_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "description", "due_at", "position", "schedule", "next_run_at", "max_retries", "interval_minutes"}
        changed = {key: value for key, value in fields.items() if key in allowed}
        if "title" in changed:
            changed["title"] = self._clean_title(str(changed["title"]), "任务标题")
        if "description" in changed and changed["description"] is not None:
            changed["description"] = str(changed["description"]).strip()
        if "due_at" in changed and changed["due_at"] is not None:
            changed["due_at"] = str(changed["due_at"]).strip() or None
        if "position" in changed and (not isinstance(changed["position"], int) or changed["position"] < 0):
            raise ValueError("任务排序必须是非负整数")
        with self.database.connect() as db:
            current = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not current:
                raise KeyError("任务不存在")
            self._validate_schedule(changed.get("schedule", current["schedule"]), changed.get("next_run_at", current["next_run_at"]), changed.get("max_retries", current["max_retries"]), changed.get("interval_minutes", current["interval_minutes"]))
            if not changed:
                return self._row(current)
            assignments = ",".join(f"{key}=?" for key in changed)
            db.execute(f"UPDATE tasks SET {assignments},updated_at=? WHERE id=?", (*changed.values(), self._now(), task_id))
            self._event(db, int(current["goal_id"]), task_id, "task.updated", {"fields": changed})
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    @staticmethod
    def _validate_schedule(schedule: Any, next_run_at: Any, max_retries: Any, interval_minutes: Any) -> None:
        if schedule not in {"manual", "once", "interval"}:
            raise ValueError("任务计划类型无效")
        if schedule != "manual" and not str(next_run_at or "").strip():
            raise ValueError("定时任务必须提供下次运行时间")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 10:
            raise ValueError("最大重试次数必须在 0 到 10 之间")
        if not isinstance(interval_minutes, int) or not 0 <= interval_minutes <= 525600:
            raise ValueError("任务间隔必须在 0 到 525600 分钟之间")
        if schedule == "interval" and interval_minutes < 1:
            raise ValueError("循环任务的间隔至少为 1 分钟")

    def set_task_status(self, task_id: int, status: str) -> dict[str, Any]:
        if status not in TASK_STATUSES:
            raise ValueError("任务状态无效")
        with self.database.connect() as db:
            current = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not current:
                raise KeyError("任务不存在")
            previous = current["status"]
            if previous == status:
                return self._row(current)
            if status not in TASK_TRANSITIONS[previous]:
                raise ValueError(f"任务不能从 {previous} 变更为 {status}")
            now = self._now()
            completed_at = now if status == "completed" else None
            db.execute("UPDATE tasks SET status=?,completed_at=?,updated_at=? WHERE id=?", (status, completed_at, now, task_id))
            self._event(db, int(current["goal_id"]), task_id, "task.status_changed", {"from": previous, "to": status})
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def events(self, goal_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.database.rows(
            "SELECT id,goal_id,task_id,created_at,kind,payload FROM task_events WHERE goal_id=? ORDER BY id DESC LIMIT ?",
            (goal_id, max(1, min(limit, 500))),
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"] or "{}")
        return rows
