from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.database import Database
from core.secretary.goals import GoalService
from core.secretary.notifications import NotificationService
from core.secretary.runner import TaskRunner


class TaskRunnerTests(TestCase):
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
