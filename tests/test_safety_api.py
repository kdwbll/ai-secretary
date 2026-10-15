from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import core.secretary.app as api
from core.secretary.auth import AccessControl
from core.secretary.database import Database
from core.secretary.memory import MemoryEngine
from core.secretary.runtime import ServiceRuntime
from core.secretary.safety import ApprovalService
from core.secretary.storage import LocalStorage


def _client(directory: str):
    database = Database(Path(directory) / "api.db")
    access = AccessControl(database)
    safety = ApprovalService(database)
    memory = MemoryEngine(LocalStorage(Path(directory) / "memory"), database)
    memory.initialize()
    client = TestClient(api.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
    return database, access, safety, memory, client


def test_approval_api_denial_duplicate_and_audit_export():
    with TemporaryDirectory() as directory:
        database, access, safety, memory, client = _client(directory)
        with patch.object(api, "DB", database), patch.object(api, "ACCESS", access), patch.object(api, "SAFETY", safety), \
             patch.object(api, "MEMORY", memory), patch.object(api, "RUNTIME", ServiceRuntime()):
            token = client.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": "Bearer " + token, "X-Idempotency-Key": "api-approval"}
            created = client.post("/api/approvals", headers=headers, json={
                "action_type": "mail.send", "level": "write", "connector": "email",
                "summary": "发送邮件", "target": "example@example.com", "exact_payload": {"subject": "测试"},
            })
            assert created.status_code == 200
            assert client.post("/api/approvals", headers=headers, json={
                "action_type": "mail.send", "level": "write", "summary": "重复"
            }).json()["id"] == created.json()["id"]
            endpoint = f"/api/approvals/{created.json()['id']}/decision"
            assert client.post(endpoint, headers={"Authorization": "Bearer " + token}, json={"decision": "deny"}).status_code == 200
            assert client.post(endpoint, headers={"Authorization": "Bearer " + token}, json={"decision": "approve"}).status_code == 409
            audit = client.get("/api/audit/export", headers={"Authorization": "Bearer " + token})
            assert audit.status_code == 200
            assert audit.json()["integrity"]["valid"] is True
            assert len(audit.json()["audit"]) == 2


def test_forget_requires_separate_approval_and_executes_once():
    with TemporaryDirectory() as directory:
        database, access, safety, memory, client = _client(directory)
        memory.upsert_fact("interests.md", "兴趣与娱乐", "喜欢测试关键词", "测试")
        with patch.object(api, "DB", database), patch.object(api, "ACCESS", access), patch.object(api, "SAFETY", safety), \
             patch.object(api, "MEMORY", memory), patch.object(api, "RUNTIME", ServiceRuntime()):
            token = client.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": "Bearer " + token, "X-Idempotency-Key": "forget-api"}
            requested = client.post("/api/forget", headers=headers, json={"phrase": "测试关键词"})
            approval_id = requested.json()["id"]
            assert "测试关键词" in memory.storage.read_text("interests.md")
            assert client.post(f"/api/forget/{approval_id}/execute", headers={"Authorization": "Bearer " + token}).status_code == 409
            assert client.post(f"/api/approvals/{approval_id}/decision", headers={"Authorization": "Bearer " + token}, json={"decision": "approve"}).status_code == 200
            executed = client.post(f"/api/forget/{approval_id}/execute", headers={"Authorization": "Bearer " + token})
            assert executed.status_code == 200
            assert "测试关键词" not in memory.storage.read_text("interests.md")
            assert client.post(f"/api/forget/{approval_id}/execute", headers={"Authorization": "Bearer " + token}).status_code == 409


def test_revoked_android_connector_stops_ingest_without_deleting_history():
    with TemporaryDirectory() as directory:
        database, access, safety, memory, client = _client(directory)
        with patch.object(api, "DB", database), patch.object(api, "ACCESS", access), patch.object(api, "SAFETY", safety), \
             patch.object(api, "MEMORY", memory), patch.object(api, "RUNTIME", ServiceRuntime()):
            token = client.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": "Bearer " + token}
            database.add_event("notification", "collected", {"title": "已有通知"})
            revoked = client.put("/api/connectors/permissions/notification", headers=headers, json={"enabled": False})
            assert revoked.status_code == 200
            blocked = client.post("/api/ingest/notification", headers=headers, json={"package": "demo", "title": "新通知", "text": "内容"})
            assert blocked.status_code == 403
            assert len(database.rows("SELECT * FROM events WHERE source='notification'")) == 1
