from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.database import Database
from core.secretary.goals import GoalService
from core.secretary.notifications import NotificationService
from core.secretary.runner import TaskRunner
from core.secretary.event_hub import EventHub


class TaskRunnerTests(TestCase):
    def test_due_task_executes_and_is_not_repeated(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runner.db")
            goals = GoalService(db)
            goal = goals.create_goal("测试")
            task = goals.create_task(goal["id"], "到期提醒", schedule="once", next_run_at="2020-01-01T00:00:00+08:00")
            runner = TaskRunner(db, NotificationService(db))

            self.assertEqual(runner.wake_due(), 1)
            self.assertEqual(runner.wake_due(), 0)
            self.assertEqual(db.rows("SELECT status FROM tasks WHERE id=?", (task["id"],))[0]["status"], "completed")
            self.assertEqual(len(runner.activity(goal["id"])), 1)

    def test_event_task_only_handles_events_created_after_subscription(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runner.db")
            hub = EventHub(db)
            old = hub.publish("calendar", "calendar", {"title": "旧日程"})
            goals = GoalService(db)
            goal = goals.create_goal("测试")
            task = goals.create_task(goal["id"], "日程变化", schedule="event", event_source="calendar")
            new = hub.publish("calendar", "calendar", {"title": "新日程"})
            runner = TaskRunner(db, NotificationService(db))

            runner.wake_events()

            runs = db.rows("SELECT source_event_id FROM task_runs WHERE task_id=?", (task["id"],))
            self.assertEqual([row["source_event_id"] for row in runs], [new["id"]])
            self.assertNotEqual(old["id"], new["id"])

            goals.update_task(task["id"], {"event_kind": "calendar"})
            latest = hub.publish("calendar", "calendar", {"title": "更新规则后的日程"})
            runner.wake_events()
            runs = db.rows("SELECT source_event_id FROM task_runs WHERE task_id=? ORDER BY id", (task["id"],))
            self.assertEqual([row["source_event_id"] for row in runs], [new["id"], latest["id"]])

    def test_restart_recovery_is_recorded_once(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runner.db")
            goals = GoalService(db)
            goal = goals.create_goal("测试")
            task = goals.create_task(goal["id"], "中断任务")
            runner = TaskRunner(db, NotificationService(db))
            runner.start(task["id"])

            self.assertEqual(runner.recover(), 1)
            self.assertEqual(runner.recover(), 0)
            self.assertEqual(db.rows("SELECT status FROM task_runs")[0]["status"], "interrupted")
            self.assertEqual(len(db.rows("SELECT id FROM task_events WHERE kind='task.run_interrupted'")), 1)

    def test_runner_uses_asia_shanghai_timezone(self):
        self.assertTrue(TaskRunner.now().endswith("+08:00"))

    def test_interval_task_is_requeued_after_success(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runner.db")
            goals = GoalService(db)
            goal = goals.create_goal("测试")
            task = goals.create_task(
                goal["id"], "周期同步", schedule="interval",
                next_run_at="2026-10-14T00:00:00+08:00", interval_minutes=30,
            )
            runner = TaskRunner(db, NotificationService(db))
            run = runner.start(task["id"])
            self.assertEqual(runner.finish(run["id"], True)["status"], "succeeded")
            row = db.rows("SELECT status,next_run_at,retry_count FROM tasks WHERE id=?", (task["id"],))[0]
            self.assertEqual(row["status"], "pending")
            self.assertIsNotNone(row["next_run_at"])
            self.assertEqual(row["retry_count"], 0)

    def test_failure_retries_then_blocks(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runner.db")
            goals = GoalService(db)
            goal = goals.create_goal("测试")
            task = goals.create_task(goal["id"], "重试", max_retries=1)
            runner = TaskRunner(db, NotificationService(db))
            first = runner.start(task["id"])
            self.assertEqual(runner.finish(first["id"], False, error="临时错误")["status"], "failed")
            row = db.rows("SELECT status,retry_count,next_run_at FROM tasks WHERE id=?", (task["id"],))[0]
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["retry_count"], 1)
            second = runner.start(task["id"])
            runner.finish(second["id"], False, error="仍然失败")
            self.assertEqual(db.rows("SELECT status FROM tasks WHERE id=?", (task["id"],))[0]["status"], "blocked")
            self.assertEqual(len(db.rows("SELECT id FROM notifications WHERE kind='task_blocked'")), 1)
