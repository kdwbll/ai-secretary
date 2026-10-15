from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .database import Database
from .notifications import NotificationService


SHANGHAI = ZoneInfo("Asia/Shanghai")


class TaskRunner:
    """Persistent, idempotent runner for manual, timed, and event tasks."""

    def __init__(self, database: Database, notifications: NotificationService):
        self.database = database
        self.notifications = notifications

    @staticmethod
    def now() -> str:
        return datetime.now(SHANGHAI).isoformat(timespec="seconds")

    def start(self, task_id: int, trigger: str = "manual", idempotency_key: str = "", source_event_id: int | None = None) -> dict:
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute(
                "SELECT t.*,g.status AS goal_status FROM tasks t JOIN goals g ON g.id=t.goal_id WHERE t.id=?",
                (task_id,),
            ).fetchone()
            if not task:
                raise KeyError("任务不存在")
            if task["goal_status"] != "active" or not int(task["enabled"]):
                raise ValueError("任务或所属目标已暂停")
            if task["status"] not in {"pending", "blocked"}:
                raise ValueError("任务当前不能启动")
            now = self.now()
            try:
                run = db.execute(
                    "INSERT INTO task_runs(task_id,trigger,status,idempotency_key,source_event_id,started_at) VALUES(?,?,?,?,?,?)",
                    (task_id, trigger, "running", idempotency_key or None, source_event_id, now),
                )
            except sqlite3.IntegrityError:
                prior = db.execute("SELECT id,task_id,status FROM task_runs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if prior:
                    return {**dict(prior), "duplicate": True}
                raise
            db.execute("UPDATE tasks SET status='in_progress',updated_at=? WHERE id=?", (now, task_id))
            db.execute(
                "INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)",
                (task["goal_id"], task_id, run.lastrowid, now, "task.run_started", json.dumps({"trigger": trigger, "source_event_id": source_event_id}, ensure_ascii=False)),
            )
            return {"id": int(run.lastrowid), "task_id": task_id, "status": "running", "duplicate": False}

    def recover(self) -> int:
        """Return interrupted work to the queue exactly once after a restart."""
        now = self.now()
        with self.database.connect() as db:
            rows = db.execute("SELECT id,task_id FROM task_runs WHERE status='running'").fetchall()
            db.execute("UPDATE task_runs SET status='interrupted',finished_at=?,error='service restarted' WHERE status='running'", (now,))
            db.execute("UPDATE tasks SET status='pending',updated_at=? WHERE status='in_progress'", (now,))
            for row in rows:
                task = db.execute("SELECT goal_id FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
                if task:
                    db.execute(
                        "INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)",
                        (task["goal_id"], row["task_id"], row["id"], now, "task.run_interrupted", '{"reason":"service restarted"}'),
                    )
        return len(rows)

    def wake_due(self) -> int:
        now = self.now()
        candidates = self.database.rows(
            "SELECT t.id,t.next_run_at FROM tasks t JOIN goals g ON g.id=t.goal_id "
            "WHERE t.enabled=1 AND g.status='active' AND t.status='pending' "
            "AND t.next_run_at IS NOT NULL ORDER BY t.next_run_at,t.id LIMIT 100",
        )
        current = datetime.now(SHANGHAI)
        due = [row for row in candidates if self._parse_time(row["next_run_at"]) <= current][:20]
        completed = 0
        for row in due:
            try:
                run = self.start(int(row["id"]), "schedule", f"schedule:{row['id']}:{row['next_run_at']}")
                if not run.get("duplicate"):
                    self.execute(int(run["id"]))
                    completed += 1
            except ValueError:
                continue
        return completed

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)

    def wake_events(self, limit: int = 100) -> int:
        events = self.database.rows(
            "SELECT id,created_at,source,kind,payload FROM events WHERE status='pending' ORDER BY id LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        completed = 0
        for event in events:
            permission = self.database.rows(
                "SELECT enabled FROM connector_permissions WHERE connector=?", (event["source"],)
            )
            if permission and not bool(permission[0]["enabled"]):
                with self.database.connect() as db:
                    db.execute("UPDATE events SET status='processed' WHERE id=? AND status='pending'", (event["id"],))
                continue
            try:
                source_payload = json.loads(event["payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                source_payload = {"summary": "原始事件内容无法解析"}
            tasks = self.database.rows(
                "SELECT t.id FROM tasks t JOIN goals g ON g.id=t.goal_id "
                "WHERE t.enabled=1 AND g.status='active' AND t.status='pending' AND t.schedule='event' "
                "AND t.event_after_id<? AND t.event_source=? AND (t.event_kind='' OR t.event_kind=?) ORDER BY t.id",
                (event["id"], event["source"], event["kind"]),
            )
            for task in tasks:
                try:
                    run = self.start(int(task["id"]), "event", f"event:{task['id']}:{event['id']}", int(event["id"]))
                    if not run.get("duplicate"):
                        self.execute(int(run["id"]), source_payload)
                        completed += 1
                except ValueError:
                    continue
            with self.database.connect() as db:
                db.execute("UPDATE events SET status='processed' WHERE id=? AND status='pending'", (event["id"],))
        return completed

    def execute(self, run_id: int, source: dict | None = None) -> dict:
        rows = self.database.rows(
            "SELECT r.id,r.task_id,r.trigger,t.title,t.description FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?",
            (run_id,),
        )
        if not rows:
            raise KeyError("运行记录不存在")
        run = rows[0]
        body = run["description"].strip() or run["title"]
        if source:
            summary = source.get("summary") or source.get("title") or source.get("raw")
            if summary:
                body = f"{body}\n\n触发来源：{str(summary)[:500]}"
        try:
            self.notifications.publish(
                "task_due" if run["trigger"] != "event" else "task_event",
                run["title"], body, reason_key=f"task:{run['task_id']}:{run['trigger']}",
            )
            return self.finish(run_id, True, {"message": body})
        except Exception as exc:
            return self.finish(run_id, False, error=str(exc))

    def finish(self, run_id: int, success: bool, result: dict | None = None, error: str = "") -> dict:
        with self.database.connect() as db:
            run = db.execute(
                "SELECT r.*,t.goal_id,t.title,t.retry_count,t.max_retries,t.schedule,t.interval_minutes "
                "FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,),
            ).fetchone()
            if not run:
                raise KeyError("运行记录不存在")
            if run["status"] != "running":
                return {"id": run_id, "status": run["status"]}
            now, status = self.now(), "succeeded" if success else "failed"
            retry = not success and int(run["retry_count"]) < int(run["max_retries"])
            recurring = success and run["schedule"] in {"interval", "event"}
            task_status = "pending" if recurring or retry else "completed" if success else "blocked"
            if success and run["schedule"] == "interval":
                next_run = (datetime.now(SHANGHAI) + timedelta(minutes=int(run["interval_minutes"]))).isoformat(timespec="seconds")
            elif retry:
                next_run = (datetime.now(SHANGHAI) + timedelta(minutes=2 ** int(run["retry_count"]))).isoformat(timespec="seconds")
            else:
                next_run = None
            db.execute("UPDATE task_runs SET status=?,finished_at=?,result=?,error=? WHERE id=?", (status, now, json.dumps(result or {}, ensure_ascii=False), error[:2000], run_id))
            db.execute(
                "UPDATE tasks SET status=?,completed_at=?,next_run_at=?,retry_count=CASE WHEN ? THEN 0 ELSE retry_count+? END,updated_at=? WHERE id=?",
                (task_status, now if success and not recurring else None, next_run, int(success), 0 if success else 1, now, run["task_id"]),
            )
            db.execute(
                "INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)",
                (run["goal_id"], run["task_id"], run_id, now, "task.run_finished", json.dumps({"status": status, "result": result or {}, "error": error[:2000]}, ensure_ascii=False)),
            )
        if not success and not retry:
            self.notifications.publish("task_blocked", "任务需要处理", f"{run['title']}：{error or '运行失败'}", reason_key=f"blocked:{run['task_id']}")
        return {"id": run_id, "status": status}

    def pause(self, run_id: int) -> dict:
        now = self.now()
        with self.database.connect() as db:
            run = db.execute("SELECT r.*,t.goal_id FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError("运行记录不存在")
            if run["status"] != "running":
                raise ValueError("只有正在运行的任务可以暂停")
            db.execute("UPDATE task_runs SET status='paused',finished_at=?,error='paused by user' WHERE id=?", (now, run_id))
            db.execute("UPDATE tasks SET status='pending',enabled=0,updated_at=? WHERE id=?", (now, run["task_id"]))
            db.execute(
                "INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)",
                (run["goal_id"], run["task_id"], run_id, now, "task.run_paused", '{}'),
            )
        return {"id": run_id, "status": "paused"}

    def activity(self, goal_id: int | None = None, limit: int = 100) -> list[dict]:
        where, values = "", []
        if goal_id is not None:
            where, values = "WHERE g.id=?", [goal_id]
        values.append(max(1, min(limit, 500)))
        rows = self.database.rows(
            "SELECT r.id,r.task_id,r.trigger,r.status,r.source_event_id,r.started_at,r.finished_at,r.result,r.error,"
            "t.title AS task_title,t.next_run_at,t.enabled,g.id AS goal_id,g.title AS goal_title "
            "FROM task_runs r JOIN tasks t ON t.id=r.task_id JOIN goals g ON g.id=t.goal_id "
            f"{where} ORDER BY r.id DESC LIMIT ?", tuple(values),
        )
        for row in rows:
            row["result"] = json.loads(row["result"] or "{}")
            row["enabled"] = bool(row["enabled"])
        return rows
