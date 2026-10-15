from __future__ import annotations

import json
from datetime import datetime, timedelta
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

GOAL_TEMPLATES = {
    "health_followup": {"name": "体检复查", "description": "整理报告、确认复查项目并按时提醒。"},
    "exam_study": {"name": "考试复习", "description": "拆分复习范围、每日推进并在考前检查。"},
    "travel_preparation": {"name": "旅行准备", "description": "集中跟进行程、证件、预订和打包事项。"},
    "bill_subscription": {"name": "账单与订阅检查", "description": "定期检查账单、续费和不再需要的订阅。"},
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

    def templates(self) -> list[dict[str, Any]]:
        return [{"id": key, **value} for key, value in GOAL_TEMPLATES.items()]

    def create_from_template(self, template_id: str, *, title: str = "", due_at: Optional[str] = None,
                             idempotency_key: Optional[str] = None) -> dict[str, Any]:
        if template_id not in GOAL_TEMPLATES:
            raise KeyError("目标模板不存在")
        template = GOAL_TEMPLATES[template_id]
        key = (idempotency_key or f"template:{template_id}:{title}:{due_at}").strip()
        goal = self.create_goal(title.strip() or template["name"], template["description"], due_at, key)
        now = datetime.now().astimezone()
        definitions = {
            "health_followup": [
                ("整理体检报告与异常指标", "manual", None, 0, "", ""),
                ("确认医院、科室与复查材料", "manual", None, 0, "", ""),
                ("复查前提醒", "once", (now + timedelta(days=7)).isoformat(timespec="seconds"), 0, "", ""),
            ],
            "exam_study": [
                ("列出考试范围与薄弱点", "manual", None, 0, "", ""),
                ("每日复习提醒", "interval", (now + timedelta(days=1)).isoformat(timespec="seconds"), 1440, "", ""),
                ("完成一次模拟测试", "manual", None, 0, "", ""),
            ],
            "travel_preparation": [
                ("确认交通与住宿", "manual", None, 0, "", ""),
                ("关注新的行程邮件", "event", None, 0, "email", "collected"),
                ("出发前检查证件与行李", "once", (now + timedelta(days=7)).isoformat(timespec="seconds"), 0, "", ""),
            ],
            "bill_subscription": [
                ("整理当前订阅清单", "manual", None, 0, "", ""),
                ("每月检查账单与续费", "interval", (now + timedelta(days=30)).isoformat(timespec="seconds"), 43200, "", ""),
                ("标记需要取消或降级的服务", "manual", None, 0, "", ""),
            ],
        }
        for index, (task_title, schedule, next_run, interval, event_source, event_kind) in enumerate(definitions[template_id]):
            self.create_task(
                int(goal["id"]), task_title, position=index + 1, idempotency_key=f"{key}:task:{index}",
                schedule=schedule, next_run_at=next_run, interval_minutes=interval,
                event_source=event_source, event_kind=event_kind,
            )
        return self.goal(int(goal["id"]))

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
                    position: Optional[int] = None, idempotency_key: Optional[str] = None, schedule: str = "manual", next_run_at: Optional[str] = None, max_retries: int = 3, interval_minutes: int = 0,
                    event_source: str = "", event_kind: str = "", enabled: bool = True) -> dict[str, Any]:
        title = self._clean_title(title, "任务标题")
        self._validate_schedule(schedule, next_run_at, max_retries, interval_minutes, event_source)
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
            event_after_id = int(db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]) if schedule == "event" else 0
            cursor = db.execute(
                "INSERT INTO tasks(goal_id,title,description,status,due_at,position,created_at,updated_at,idempotency_key,schedule,next_run_at,max_retries,interval_minutes,event_source,event_kind,event_after_id,enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (goal_id, title, description.strip(), "pending", due_at, position, now, now, key, schedule, next_run_at, max_retries, interval_minutes, event_source.strip(), event_kind.strip(), event_after_id, int(enabled)),
            )
            task_id = int(cursor.lastrowid)
            self._event(db, goal_id, task_id, "task.created", {"title": title, "due_at": due_at, "position": position})
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def update_task(self, task_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "description", "due_at", "position", "schedule", "next_run_at", "max_retries", "interval_minutes", "event_source", "event_kind", "enabled"}
        changed = {key: value for key, value in fields.items() if key in allowed}
        if "title" in changed:
            changed["title"] = self._clean_title(str(changed["title"]), "任务标题")
        if "description" in changed and changed["description"] is not None:
            changed["description"] = str(changed["description"]).strip()
        if "due_at" in changed and changed["due_at"] is not None:
            changed["due_at"] = str(changed["due_at"]).strip() or None
        if "position" in changed and (not isinstance(changed["position"], int) or changed["position"] < 0):
            raise ValueError("任务排序必须是非负整数")
        for key in ("event_source", "event_kind"):
            if key in changed:
                changed[key] = str(changed[key] or "").strip()
        if "enabled" in changed:
            changed["enabled"] = int(bool(changed["enabled"]))
        with self.database.connect() as db:
            current = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not current:
                raise KeyError("任务不存在")
            self._validate_schedule(changed.get("schedule", current["schedule"]), changed.get("next_run_at", current["next_run_at"]), changed.get("max_retries", current["max_retries"]), changed.get("interval_minutes", current["interval_minutes"]), changed.get("event_source", current["event_source"]))
            final_schedule = changed.get("schedule", current["schedule"])
            if final_schedule == "event" and {"schedule", "event_source", "event_kind"} & changed.keys():
                changed["event_after_id"] = int(db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0])
            if not changed:
                return self._row(current)
            assignments = ",".join(f"{key}=?" for key in changed)
            db.execute(f"UPDATE tasks SET {assignments},updated_at=? WHERE id=?", (*changed.values(), self._now(), task_id))
            self._event(db, int(current["goal_id"]), task_id, "task.updated", {"fields": changed})
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    @staticmethod
    def _validate_schedule(schedule: Any, next_run_at: Any, max_retries: Any, interval_minutes: Any, event_source: Any = "") -> None:
        if schedule not in {"manual", "once", "interval", "event"}:
            raise ValueError("任务计划类型无效")
        if schedule in {"once", "interval"} and not str(next_run_at or "").strip():
            raise ValueError("定时任务必须提供下次运行时间")
        if schedule in {"once", "interval"}:
            try:
                datetime.fromisoformat(str(next_run_at))
            except ValueError as exc:
                raise ValueError("下次运行时间格式无效") from exc
        if schedule == "event" and not str(event_source or "").strip():
            raise ValueError("事件任务必须选择事件来源")
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
