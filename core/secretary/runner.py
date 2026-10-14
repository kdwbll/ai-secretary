from __future__ import annotations

import json
from datetime import datetime, timedelta

from .database import Database
from .notifications import NotificationService


class TaskRunner:
    """Database-backed task run state; schedulers only call this service."""
    def __init__(self, database: Database, notifications: NotificationService): self.database, self.notifications = database, notifications
    @staticmethod
    def now() -> str: return datetime.now().astimezone().isoformat(timespec="seconds")
    def start(self, task_id: int, trigger: str = "manual") -> dict:
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT id,goal_id,title,status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task: raise KeyError("任务不存在")
            if task["status"] not in {"pending", "blocked"}: raise ValueError("任务当前不能启动")
            now = self.now()
            run = db.execute("INSERT INTO task_runs(task_id,trigger,status,started_at) VALUES(?,?,?,?)", (task_id, trigger, "running", now))
            db.execute("UPDATE tasks SET status='in_progress',updated_at=? WHERE id=?", (now, task_id))
            db.execute("INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)", (task["goal_id"],task_id,run.lastrowid,now,"task.run_started",json.dumps({"trigger":trigger},ensure_ascii=False)))
            return {"id": int(run.lastrowid), "task_id": task_id, "status": "running"}
    def recover(self) -> int:
        """Return interrupted in-process work to the queue on service startup."""
        now = self.now()
        with self.database.connect() as db:
            count = db.execute("UPDATE task_runs SET status='interrupted',finished_at=?,error='service restarted' WHERE status='running'", (now,)).rowcount
            db.execute("UPDATE tasks SET status='pending',updated_at=? WHERE status='in_progress'", (now,))
        return int(count)
    def wake_due(self) -> int:
        now = self.now()
        due = self.database.rows("SELECT id FROM tasks WHERE status='pending' AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at LIMIT 10", (now,))
        started = 0
        for row in due:
            try: self.start(int(row["id"]), "schedule"); started += 1
            except ValueError: pass
        return started
    def finish(self, run_id: int, success: bool, result: dict | None = None, error: str = "") -> dict:
        with self.database.connect() as db:
            run = db.execute("SELECT r.*,t.goal_id,t.title,t.retry_count,t.max_retries,t.schedule,t.interval_minutes FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
            if not run: raise KeyError("运行记录不存在")
            if run["status"] != "running": return {"id":run_id,"status":run["status"]}
            now, status = self.now(), "succeeded" if success else "failed"
            retry = not success and int(run["retry_count"]) < int(run["max_retries"])
            recurring = success and run["schedule"] == "interval"
            task_status = "pending" if recurring or retry else "completed" if success else "blocked"
            if recurring:
                next_run = (datetime.now().astimezone() + timedelta(minutes=int(run["interval_minutes"]))).isoformat(timespec="seconds")
            elif retry:
                next_run = (datetime.now().astimezone() + timedelta(minutes=2 ** int(run["retry_count"]))).isoformat(timespec="seconds")
            else:
                next_run = None
            db.execute("UPDATE task_runs SET status=?,finished_at=?,result=?,error=? WHERE id=?", (status,now,json.dumps(result or {},ensure_ascii=False),error[:2000],run_id))
            db.execute("UPDATE tasks SET status=?,completed_at=?,next_run_at=?,retry_count=CASE WHEN ? THEN 0 ELSE retry_count+? END,updated_at=? WHERE id=?", (task_status,now if success and not recurring else None,next_run,int(success),0 if success else 1,now,run["task_id"]))
            db.execute("INSERT INTO task_events(goal_id,task_id,run_id,created_at,kind,payload) VALUES(?,?,?,?,?,?)", (run["goal_id"],run["task_id"],run_id,now,"task.run_finished",json.dumps({"status":status},ensure_ascii=False)))
        if not success and not retry: self.notifications.publish("task_blocked", "任务需要处理", f"{run['title']}：{error or '运行失败'}")
        return {"id":run_id,"status":status}
