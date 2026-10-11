from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from email.message import Message
from email.policy import default
from html.parser import HTMLParser
from typing import Any, Iterator


MAX_BODY_CHARS = 100_000
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 50 * 1024 * 1024


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part for part, charset in parts)


class _ReadableHtml(HTMLParser):
    BREAK_TAGS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "head"}:
            self.ignored += 1
        elif not self.ignored and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"} and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts).replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n\s*\n\s*\n+", "\n\n", value)
        return value.strip()


def html_to_text(value: str) -> str:
    parser = _ReadableHtml()
    parser.feed(value)
    parser.close()
    return parser.text()


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _body_text(message: Message) -> str:
    if message.is_multipart():
        parts = list(message.iter_parts()) if hasattr(message, "iter_parts") else list(message.get_payload())
        if message.get_content_subtype() == "alternative":
            candidates = [(_body_text(part), part.get_content_type()) for part in parts]
            for content_type in ("text/plain", "text/html"):
                for text, candidate_type in candidates:
                    if candidate_type == content_type and text.strip():
                        return text
            return next((text for text, _ in candidates if text.strip()), "")
        return "\n\n".join(filter(None, (_body_text(part) for part in parts)))

    disposition = (message.get_content_disposition() or "").lower() if hasattr(message, "get_content_disposition") else ""
    if disposition == "attachment" or message.get_filename():
        return ""
    content_type = message.get_content_type()
    if content_type == "message/rfc822":
        nested = message.get_payload()
        if isinstance(nested, list):
            return "\n\n".join(_body_text(item) for item in nested)
        return ""
    if not content_type.startswith("text/"):
        return ""
    text = _part_text(message)
    return html_to_text(text) if content_type == "text/html" else text.strip()


def parse_message(raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw, policy=default)
    attachments: list[dict[str, Any]] = []
    total_bytes = 0
    for part in message.walk():
        filename = _decode(part.get_filename() or "")
        disposition = (part.get_content_disposition() or "").lower() if hasattr(part, "get_content_disposition") else ""
        if not filename and disposition != "attachment":
            continue
        content = part.get_payload(decode=True) or b""
        if not content and part.get_content_type() == "message/rfc822":
            content = part.as_bytes(policy=default)
        if not content or len(content) > MAX_ATTACHMENT_BYTES or total_bytes + len(content) > MAX_TOTAL_ATTACHMENT_BYTES:
            attachments.append({"name": filename or "未命名附件", "content_type": part.get_content_type(), "data": b"", "skipped": True})
            continue
        total_bytes += len(content)
        attachments.append({"name": filename or "未命名附件", "content_type": part.get_content_type(), "data": content, "skipped": False})
    return {
        "uid": message.get("Message-ID") or "",
        "subject": _decode(message.get("Subject", "")),
        "from": _decode(message.get("From", "")),
        "date": message.get("Date", ""),
        "body": _body_text(message)[:MAX_BODY_CHARS],
        "attachments": attachments,
    }


class ImapConnector:
    """Read-only IMAP connector. QQ Mail requires an authorization code, never the account password."""

    def __init__(self, host: str, username: str, authorization_code: str, port: int = 993):
        self.host, self.port, self.username, self.authorization_code = host, port, username, authorization_code

    def unread(self, limit: int = 20) -> Iterator[dict[str, Any]]:
        yield from self._messages("UNSEEN", limit)

    def recent(self, limit: int = 20) -> Iterator[dict[str, Any]]:
        yield from self._messages("ALL", limit)

    def _messages(self, criterion: str, limit: int) -> Iterator[dict[str, Any]]:
        with imaplib.IMAP4_SSL(self.host, self.port) as client:
            client.login(self.username, self.authorization_code)
            client.select("INBOX", readonly=True)
            status, data = client.search(None, criterion)
            if status != "OK":
                return
            for message_id in data[0].split()[-limit:]:
                status, parts = client.fetch(message_id, "(RFC822)")
                if status != "OK":
                    continue
                raw = next((part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
                if raw is None:
                    continue
                parsed = parse_message(raw)
                parsed["uid"] = parsed["uid"] or message_id.decode(errors="replace")
                yield parsed
