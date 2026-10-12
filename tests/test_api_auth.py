from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi.testclient import TestClient

from core.secretary.auth import AccessControl
from core.secretary.database import Database
import core.secretary.app as app_module


class ApiAuthenticationTests(TestCase):
    def test_remote_device_must_pair_and_revocation_takes_effect(self):
        with TemporaryDirectory() as directory:
            original_access = app_module.ACCESS
            app_module.ACCESS = AccessControl(Database(Path(directory) / "auth.db"))
            try:
                local = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
                remote = TestClient(app_module.app, base_url="http://192.168.1.50:8765", client=("192.168.1.50", 50001))

                self.assertEqual(remote.get("/api/chats?limit=1").status_code, 401)
                local_token = local.get("/api/auth/local-token").json()["token"]
                local_headers = {"Authorization": f"Bearer {local_token}"}
                code = local.post("/api/auth/pairing-code", headers=local_headers).json()["code"]
                paired = remote.post(
                    "/api/auth/pair",
                    json={"code": code, "device_name": "test phone"},
                )
                self.assertEqual(paired.status_code, 200)
                token = paired.json()["token"]
                headers = {"Authorization": f"Bearer {token}"}
                self.assertEqual(remote.get("/api/chats?limit=1", headers=headers).status_code, 200)

                token_id = paired.json()["id"]
                self.assertEqual(local.delete(f"/api/auth/devices/{token_id}", headers=local_headers).status_code, 200)
                self.assertEqual(remote.get("/api/chats?limit=1", headers=headers).status_code, 401)
            finally:
                app_module.ACCESS = original_access

    def test_remote_cannot_generate_pairing_code(self):
        remote = TestClient(app_module.app, base_url="http://192.168.1.50:8765", client=("192.168.1.50", 50001))
        self.assertEqual(remote.post("/api/auth/pairing-code").status_code, 401)

    def test_local_service_can_pause_and_resume_writes(self):
        app_module.RUNTIME.resume()
        local = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        try:
            token = local.get("/api/auth/local-token").json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
            self.assertEqual(local.get("/api/service/status", headers=headers).json()["state"], "running")
            self.assertEqual(local.post("/api/service/pause", headers=headers).json()["state"], "paused")
            self.assertEqual(local.post("/api/chat", headers=headers, json={"message": "测试"}).status_code, 423)
            self.assertEqual(local.post("/api/service/resume", headers=headers).json()["state"], "running")
        finally:
            app_module.RUNTIME.resume()

    def test_rejects_untrusted_host_names_and_malformed_hosts(self):
        client = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        self.assertEqual(client.get("/api/health", headers={"Host": "attacker.example"}).status_code, 400)
        self.assertEqual(client.get("/api/health", headers={"Host": "localhost.attacker.example"}).status_code, 400)
        self.assertEqual(client.get("/api/health", headers={"Host": "[::1]:not-a-port"}).status_code, 400)

    def test_rejects_cross_origin_requests_even_with_a_valid_token(self):
        client = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        token = client.get("/api/auth/local-token").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Origin": "http://attacker.example"}
        self.assertEqual(client.post("/api/auth/pairing-code", headers=headers).status_code, 403)

    def test_cookie_authenticated_writes_require_same_origin(self):
        client = TestClient(app_module.app, base_url="http://localhost:8765", client=("127.0.0.1", 50000))
        token_response = client.get("/api/auth/local-token")
        self.assertEqual(token_response.status_code, 200)
        self.assertEqual(client.post("/api/auth/pairing-code").status_code, 403)
        allowed = client.post("/api/auth/pairing-code", headers={"Origin": "http://localhost:8765"})
        self.assertEqual(allowed.status_code, 200)

    def test_private_lan_host_and_native_bearer_request_are_allowed(self):
        client = TestClient(app_module.app, base_url="http://192.168.1.20:8765", client=("192.168.1.50", 50001))
        self.assertEqual(client.get("/api/chats?limit=1").status_code, 401)
        local = TestClient(app_module.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        token = local.get("/api/auth/local-token").json()["token"]
        # Native Android clients use an explicit Bearer token and do not send
        # the browser-only Origin header.
        self.assertEqual(client.get("/api/chats?limit=1", headers={"Authorization": f"Bearer {token}"}).status_code, 200)
