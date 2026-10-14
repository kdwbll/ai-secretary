from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi.testclient import TestClient

from core.secretary.auth import AccessControl
from core.secretary.database import Database
from core.secretary.goals import GoalService
import core.secretary.app as app_module


class GoalServiceTests(TestCase):
    def test_goal_task_lifecycle_is_idempotent_and_audited(self):
        with TemporaryDirectory() as directory:
            service = GoalService(Database(Path(directory) / "goals.db"))
            goal = service.create_goal("完成课程", "复习并报名", "2026-11-01", "goal-1")
            self.assertEqual(goal["status"], "active")
            self.assertEqual(service.create_goal("不会重复", idempotency_key="goal-1")["id"], goal["id"])

            task = service.create_task(goal["id"], "整理笔记", idempotency_key="task-1")
            self.assertEqual(service.create_task(goal["id"], "不会重复", idempotency_key="task-1")["id"], task["id"])
            self.assertEqual(service.set_task_status(task["id"], "in_progress")["status"], "in_progress")
            self.assertEqual(service.set_task_status(task["id"], "completed")["status"], "completed")
            self.assertEqual(service.set_goal_status(goal["id"], "completed")["status"], "completed")

            with self.assertRaisesRegex(ValueError, "不能从 completed"):
                service.set_goal_status(goal["id"], "active")
            events = service.events(goal["id"])
            self.assertEqual([item["kind"] for item in events], ["goal.status_changed", "task.status_changed", "task.status_changed", "task.created", "goal.created"])

    def test_unknown_goal_and_invalid_transition_are_rejected(self):
        with TemporaryDirectory() as directory:
            service = GoalService(Database(Path(directory) / "goals.db"))
            with self.assertRaisesRegex(KeyError, "目标不存在"):
                service.create_task(999, "不存在的目标")
            goal = service.create_goal("测试")
            # Repeating the requested state is safe for retried mobile/web requests.
            self.assertEqual(service.set_goal_status(goal["id"], "active")["status"], "active")
            service.set_goal_status(goal["id"], "completed")
            with self.assertRaisesRegex(ValueError, "不能从 completed"):
                service.set_goal_status(goal["id"], "active")


class GoalApiTests(TestCase):
    def test_authenticated_goal_api_round_trip(self):
        with TemporaryDirectory() as directory:
            original_access, original_goals = app_module.ACCESS, app_module.GOALS
            database = Database(Path(directory) / "api.db")
            app_module.ACCESS = AccessControl(database)
            app_module.GOALS = GoalService(database)
            try:
                client = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
                token = client.get("/api/auth/local-token").json()["token"]
                headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "goal-api-1"}
                created = client.post("/api/goals", headers=headers, json={"title": "准备旅行", "due_at": "2026-12-01"})
                self.assertEqual(created.status_code, 200)
                goal_id = created.json()["id"]
                self.assertEqual(client.post("/api/goals", headers=headers, json={"title": "重复"}).json()["id"], goal_id)
                task = client.post(f"/api/goals/{goal_id}/tasks", headers={"Authorization": f"Bearer {token}"}, json={"title": "订酒店"})
                self.assertEqual(task.status_code, 200)
                self.assertEqual(client.post(f"/api/tasks/{task.json()['id']}/status", headers={"Authorization": f"Bearer {token}"}, json={"status": "completed"}).status_code, 200)
                detail = client.get(f"/api/goals/{goal_id}", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["tasks"][0]["status"], "completed")
            finally:
                app_module.ACCESS, app_module.GOALS = original_access, original_goals
