from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path


class SecretStore:
    """Small local authenticated-encryption store.

    The database only contains versioned ciphertext.  The 256-bit installation
    key lives in a permission-restricted file beside the database, so copying a
    SQLite file does not disclose provider or mailbox credentials.
    """

    PREFIX = "enc:v1:"

    def __init__(self, key_path: Path):
        self.key_path = key_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(str(self.key_path), flags, 0o600)
            try:
                os.write(descriptor, base64.urlsafe_b64encode(os.urandom(32)))
            finally:
                os.close(descriptor)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        raw = base64.urlsafe_b64decode(self.key_path.read_bytes())
        if len(raw) != 32:
            raise RuntimeError("本机密钥文件损坏，请从备份恢复")
        self._enc_key = hmac.new(raw, b"second-brain/encryption", hashlib.sha256).digest()
        self._mac_key = hmac.new(raw, b"second-brain/authentication", hashlib.sha256).digest()

    def encrypt(self, value: str) -> str:
        if not value or value.startswith(self.PREFIX):
            return value
        nonce = os.urandom(16)
        plain = value.encode("utf-8")
        stream = self._keystream(nonce, len(plain))
        cipher = bytes(left ^ right for left, right in zip(plain, stream))
        tag = hmac.new(self._mac_key, nonce + cipher, hashlib.sha256).digest()
        return self.PREFIX + base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value or not value.startswith(self.PREFIX):
            return value
        try:
            payload = base64.urlsafe_b64decode(value[len(self.PREFIX):].encode("ascii"))
            nonce, cipher, tag = payload[:16], payload[16:-32], payload[-32:]
            expected = hmac.new(self._mac_key, nonce + cipher, hashlib.sha256).digest()
            if len(nonce) != 16 or not hmac.compare_digest(tag, expected):
                raise ValueError
            stream = self._keystream(nonce, len(cipher))
            return bytes(left ^ right for left, right in zip(cipher, stream)).decode("utf-8")
        except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
            raise RuntimeError("本机加密数据校验失败") from exc

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(hmac.new(self._enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(output[:length])

    def migrate_database(self, database) -> None:
        """Encrypt legacy plaintext credentials in one atomic transaction."""
        with database.connect() as db:
            for row in db.execute("SELECT id,api_key FROM providers WHERE api_key<>''").fetchall():
                encrypted = self.encrypt(row["api_key"])
                if encrypted != row["api_key"]:
                    db.execute("UPDATE providers SET api_key=? WHERE id=?", (encrypted, row["id"]))
            for row in db.execute("SELECT id,authorization_code FROM email_accounts WHERE authorization_code<>''").fetchall():
                encrypted = self.encrypt(row["authorization_code"])
                if encrypted != row["authorization_code"]:
                    db.execute("UPDATE email_accounts SET authorization_code=? WHERE id=?", (encrypted, row["id"]))
            for key in ("map_api_key", "map_security_code", "map_web_service_key"):
                row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if row and row["value"]:
                    db.execute("UPDATE settings SET value=? WHERE key=?", (self.encrypt(row["value"]), key))
