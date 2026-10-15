from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime
from typing import Any, Optional

from .database import Database


ARTIFACT_KINDS = {"plan", "checklist", "timeline", "budget"}


class ArtifactConflict(ValueError):
    pass


class ArtifactService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["user_edited"] = bool(row.get("user_edited"))
        return row

    def create(self, kind: str, title: str, content: str, *, mime_type: str = "text/markdown", source: str = "",
               goal_id: Optional[int] = None, chat_id: Optional[int] = None, actor: str = "assistant") -> dict[str, Any]:
        if kind not in ARTIFACT_KINDS:
            raise ValueError("Artifact 类型无效")
        if not title.strip() or not content.strip():
            raise ValueError("Artifact 标题和内容不能为空")
        now = self._now()
        with self.database.connect() as db:
            cursor = db.execute(
                "INSERT INTO artifacts(goal_id,chat_id,kind,title,mime_type,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (goal_id, chat_id, kind, title.strip(), mime_type.strip() or "text/markdown", source.strip(), now, now),
            )
            artifact_id = int(cursor.lastrowid)
            db.execute("INSERT INTO artifact_versions(artifact_id,version,content,created_at,actor,source) VALUES(?,1,?,?,?,?)",
                       (artifact_id, content, now, actor, source.strip()))
        return self.get(artifact_id)

    def get(self, artifact_id: int) -> dict[str, Any]:
        rows = self.database.rows(
            "SELECT a.*,v.content,v.actor AS version_actor,v.created_at AS version_created_at "
            "FROM artifacts a JOIN artifact_versions v ON v.artifact_id=a.id AND v.version=a.current_version WHERE a.id=?", (artifact_id,),
        )
        if not rows:
            raise KeyError("Artifact 不存在")
        item = self._decode(rows[0])
        item["versions"] = self.database.rows(
            "SELECT version,created_at,actor,source FROM artifact_versions WHERE artifact_id=? ORDER BY version DESC", (artifact_id,),
        )
        return item

    def list(self, goal_id: Optional[int] = None) -> list[dict[str, Any]]:
        where, params = ("WHERE a.goal_id=?", (goal_id,)) if goal_id is not None else ("", ())
        rows = self.database.rows(
            "SELECT a.*,substr(v.content,1,500) AS preview FROM artifacts a "
            "JOIN artifact_versions v ON v.artifact_id=a.id AND v.version=a.current_version "
            f"{where} ORDER BY a.updated_at DESC,a.id DESC", params,
        )
        return [self._decode(row) for row in rows]

    def update(self, artifact_id: int, content: str, *, base_version: int, actor: str = "user", source: str = "manual edit", confirm_overwrite: bool = False) -> dict[str, Any]:
        with self.database.connect() as db:
            current = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
            if not current:
                raise KeyError("Artifact 不存在")
            if int(current["current_version"]) != base_version:
                raise ArtifactConflict("Artifact 已有新版本，请刷新后再编辑")
            if actor != "user" and int(current["user_edited"]) and not confirm_overwrite:
                raise ArtifactConflict("用户已经编辑过此 Artifact，需要确认后才能刷新")
            version = base_version + 1
            now = self._now()
            db.execute("INSERT INTO artifact_versions(artifact_id,version,content,created_at,actor,source) VALUES(?,?,?,?,?,?)",
                       (artifact_id, version, content, now, actor, source))
            db.execute("UPDATE artifacts SET current_version=?,updated_at=?,user_edited=?,render_status='ready',render_error='' WHERE id=?",
                       (version, now, int(actor == "user" or current["user_edited"]), artifact_id))
        return self.get(artifact_id)

    def delete(self, artifact_id: int) -> None:
        with self.database.connect() as db:
            cursor = db.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))
            if cursor.rowcount != 1:
                raise KeyError("Artifact 不存在")

    def render_html(self, artifact_id: int) -> str:
        item = self.get(artifact_id)
        content = html.escape(item["content"])
        lines = content.splitlines()
        body = "".join(f"<p>{line or '&nbsp;'}</p>" for line in lines)
        return f"<!doctype html><meta charset='utf-8'><title>{html.escape(item['title'])}</title><style>body{{font:16px/1.7 system-ui;max-width:900px;margin:40px auto;padding:0 24px;color:#1f2924}}p{{margin:.45em 0;white-space:pre-wrap}}</style><h1>{html.escape(item['title'])}</h1>{body}"

    def export(self, artifact_id: int, format: str) -> tuple[bytes, str, str]:
        item = self.get(artifact_id)
        if format == "html":
            return self.render_html(artifact_id).encode("utf-8"), "text/html; charset=utf-8", f"artifact-{artifact_id}.html"
        if format == "csv" and item["kind"] == "budget":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["预算看板", item["title"]])
            for line in item["content"].splitlines():
                writer.writerow([line])
            return output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"artifact-{artifact_id}.csv"
        return item["content"].encode("utf-8"), "text/markdown; charset=utf-8", f"artifact-{artifact_id}.md"


def safe_file_preview(name: str, extracted_text: str) -> str:
    title = html.escape(name)
    content = html.escape(extracted_text or "没有可预览的文字内容")
    return (
        "<!doctype html><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; frame-src 'none'\">"
        f"<title>{title}</title><style>body{{font:15px/1.7 system-ui;max-width:980px;margin:36px auto;padding:0 24px;color:#1f2924}}"
        f"pre{{white-space:pre-wrap;word-break:break-word}}</style><h1>{title}</h1><pre>{content}</pre>"
    )
