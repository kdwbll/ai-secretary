from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
import core.secretary.app as api
from core.secretary.auth import AccessControl
from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.runtime import ServiceRuntime
from core.secretary.storage import LocalStorage


def test_confirmation_api_is_authenticated_and_accepts_only_once():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "data.db")
        memory = MemoryEngine(LocalStorage(Path(directory) / "memory"), db)
        memory.initialize()
        item = memory.queue_fact("health.md", "当前状况", "我可能对花生过敏", "2026-10-13 对话 #1", "需要确认")
        with patch.object(api, "MEMORY", memory), patch.object(api, "ACCESS", AccessControl(db)), \
             patch.object(api, "RUNTIME", ServiceRuntime()):
            client = TestClient(api.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
            endpoint = f"/api/memory-candidates/{item['id']}/resolve"
            assert client.get("/api/memory-candidates").status_code == 401
            assert client.post(endpoint, json={"accept": True}).status_code == 401
            token = client.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": "Bearer " + token}
            assert client.get("/api/memory-candidates", headers=headers).json()["candidates"][0]["id"] == item["id"]
            assert client.post(endpoint, json={"accept": True}, headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
            api.RUNTIME.pause()
            assert client.post(endpoint, json={"accept": True}, headers=headers).status_code == 423
            api.RUNTIME.resume()
            assert client.post(endpoint, json={"accept": True}, headers=headers).status_code == 200
            assert client.post(endpoint, json={"accept": True}, headers=headers).status_code == 409
            assert memory.storage.read_text("health.md").count("我可能对花生过敏") == 1
            assert client.get("/api/memory-candidates", headers=headers).json()["candidates"] == []


def test_reject_and_invalid_candidate_leave_archives_untouched():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "data.db")
        memory = MemoryEngine(LocalStorage(Path(directory) / "memory"), db)
        memory.initialize()
        before = memory.storage.read_text("habits.md")
        item = memory.queue_fact("habits.md", "运动", "我今天运动", "测试", "一次经历")
        with patch.object(api, "MEMORY", memory), patch.object(api, "ACCESS", AccessControl(db)):
            client = TestClient(api.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
            token = client.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": "Bearer " + token}
            assert client.post(f"/api/memory-candidates/{item['id']}/resolve", headers=headers, json={"accept": False}).status_code == 200
            assert memory.storage.read_text("habits.md") == before
            assert client.post("/api/memory-candidates/999/resolve", headers=headers, json={"accept": True}).status_code == 404
