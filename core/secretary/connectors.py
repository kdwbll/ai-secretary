from __future__ import annotations

import email
import imaplib
from email.header import decode_header
from typing import Iterator


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part for part, charset in parts)


class ImapConnector:
    """Read-only IMAP connector. QQ Mail requires an authorization code, never the account password."""

    def __init__(self, host: str, username: str, authorization_code: str, port: int = 993):
        self.host, self.port, self.username, self.authorization_code = host, port, username, authorization_code

    def unread(self, limit: int = 20) -> Iterator[dict[str, str]]:
        with imaplib.IMAP4_SSL(self.host, self.port) as client:
            client.login(self.username, self.authorization_code)
            client.select("INBOX", readonly=True)
            status, data = client.search(None, "UNSEEN")
            if status != "OK":
                return
            for message_id in data[0].split()[-limit:]:
                status, parts = client.fetch(message_id, "(RFC822)")
                if status != "OK":
                    continue
                message = email.message_from_bytes(parts[0][1])
                body = ""
                for part in message.walk():
                    if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                        body += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                yield {"uid": message.get("Message-ID") or message_id.decode(errors="replace"), "subject": _decode(message.get("Subject", "")), "from": _decode(message.get("From", "")), "date": message.get("Date", ""), "body": body[:50000]}
