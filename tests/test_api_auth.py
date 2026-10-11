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
                local = TestClient(app_module.app, client=("127.0.0.1", 50000))
                remote = TestClient(app_module.app, client=("192.168.1.50", 50001))

                self.assertEqual(remote.get("/api/chats?limit=1").status_code, 401)
                code = local.post("/api/auth/pairing-code").json()["code"]
                paired = remote.post(
                    "/api/auth/pair",
                    json={"code": code, "device_name": "test phone"},
                )
                self.assertEqual(paired.status_code, 200)
                token = paired.json()["token"]
                headers = {"Authorization": f"Bearer {token}"}
                self.assertEqual(remote.get("/api/chats?limit=1", headers=headers).status_code, 200)

                token_id = paired.json()["id"]
                self.assertEqual(local.delete(f"/api/auth/devices/{token_id}").status_code, 200)
                self.assertEqual(remote.get("/api/chats?limit=1", headers=headers).status_code, 401)
            finally:
                app_module.ACCESS = original_access

    def test_remote_cannot_generate_pairing_code(self):
        remote = TestClient(app_module.app, client=("192.168.1.50", 50001))
        self.assertEqual(remote.post("/api/auth/pairing-code").status_code, 401)
