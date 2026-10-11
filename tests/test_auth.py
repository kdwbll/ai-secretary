from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.secretary.auth import AccessControl
from core.secretary.database import Database


class AccessControlTests(TestCase):
    def test_pairing_token_is_hashed_and_can_be_revoked(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "data.db")
            access = AccessControl(database)
            code = access.create_pairing_code()["code"]
            result = access.pair(code, "Redmi Turbo 4 Pro")

            self.assertTrue(access.verify(result["token"]))
            stored = database.rows("SELECT name,token_hash,last_used_at FROM access_tokens")[0]
            self.assertEqual(stored["name"], "Redmi Turbo 4 Pro")
            self.assertNotEqual(stored["token_hash"], result["token"])
            self.assertNotIn(result["token"], str(stored))
            self.assertIsNotNone(stored["last_used_at"])

            self.assertTrue(access.revoke(result["id"]))
            self.assertFalse(access.verify(result["token"]))

    def test_pairing_code_is_single_use(self):
        with TemporaryDirectory() as directory:
            access = AccessControl(Database(Path(directory) / "data.db"))
            code = access.create_pairing_code()["code"]
            access.pair(code, "phone")
            with self.assertRaisesRegex(ValueError, "失效"):
                access.pair(code, "other phone")

    def test_wrong_code_does_not_issue_token(self):
        with TemporaryDirectory() as directory:
            access = AccessControl(Database(Path(directory) / "data.db"))
            code = access.create_pairing_code()["code"]
            wrong_code = "000000" if code != "000000" else "999999"
            with self.assertRaisesRegex(ValueError, "不正确"):
                access.pair(wrong_code, "phone")

    def test_loopback_detection(self):
        self.assertTrue(AccessControl.is_loopback("127.0.0.1"))
        self.assertTrue(AccessControl.is_loopback("::1"))
        self.assertFalse(AccessControl.is_loopback("192.168.1.20"))
