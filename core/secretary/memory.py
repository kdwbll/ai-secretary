from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Optional

from .database import Database
from .storage import Storage

try:
    import yaml
except ImportError:  # small fallback keeps the core testable before dependencies are installed
    yaml = None


DOMAINS = {
    "me.md": ("me", "user", "# 核心档案\n\n## 基本信息\n\n## 价值观与长期目标\n\n## 硬性规则\n\n## 早报偏好\n\n## 禁止记录\n"),
    "habits.md": ("habits", "domain", "# 生活习惯\n\n## 作息\n\n## 饮食\n\n## 运动\n"),
    "health.md": ("health", "domain", "# 健康\n\n## 当前状况\n\n## 指标与趋势\n"),
    "finance.md": ("finance", "domain", "# 财务\n\n## 收支与预算\n\n## 近期流水\n"),
    "work-study.md": ("work-study", "domain", "# 工作与学习\n\n## 当前事项\n\n## 技能与目标\n"),
    "interests.md": ("interests", "domain", "# 兴趣\n\n## 兴趣与娱乐\n\n## 常去地点\n"),
}


@dataclass
class MemoryDocument:
    path: str
    metadata: dict[str, Any]
    body: str


def _simple_yaml_load(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            result[key.strip()] = [x.strip().strip("'\"") for x in value[1:-1].split(",") if x.strip()]
        else:
            result[key.strip()] = value.strip("'\"")
    return result


class MemoryEngine:
    def __init__(self, storage: Storage, database: Database):
        self.storage = storage
        self.database = database
        self._write_lock = RLock()

    def initialize(self) -> None:
        existing = set(self.storage.list(".md"))
        for path, (doc_id, kind, body) in DOMAINS.items():
            if path not in existing:
                self.save(MemoryDocument(path, {"id": doc_id, "type": kind, "related": []}, body), "初始化记忆", "system")
        self.ensure_daily()
        self.rebuild_index()

    def parse(self, path: str) -> MemoryDocument:
        raw = self.storage.read_text(path)
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.S)
        if not match:
            raise ValueError(f"{path} 缺少合法 front matter")
        metadata = yaml.safe_load(match.group(1)) if yaml else _simple_yaml_load(match.group(1))
        metadata = metadata or {}
        if not {"id", "type", "related", "updated"}.issubset(metadata):
            raise ValueError(f"{path} front matter 字段不完整")
        return MemoryDocument(path, metadata, match.group(2).rstrip() + "\n")

    def _serialize(self, doc: MemoryDocument) -> str:
        meta = dict(doc.metadata)
        meta["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
        related = meta.get("related", []) or []
        lines = ["---", f"id: {meta['id']}", f"type: {meta['type']}", "related: [" + ", ".join(str(x) for x in related) + "]", f"updated: {meta['updated']}", "---", "", doc.body.rstrip(), ""]
        return "\n".join(lines)

    def save(self, doc: MemoryDocument, reason: str, actor: str = "AI") -> None:
        with self._write_lock:
            try:
                before = self.storage.read_text(doc.path)
            except FileNotFoundError:
                before = ""
            after = self._serialize(doc)
            if before == after:
                return
            self.storage.write_text(doc.path, after)
            self.database.record_mutation(doc.path, before, after, reason, actor)

    def ensure_daily(self, day: Optional[date] = None) -> MemoryDocument:
        with self._write_lock:
            day = day or date.today()
            path = f"daily/{day.isoformat()}.md"
            try:
                return self.parse(path)
            except FileNotFoundError:
                doc = MemoryDocument(path, {"id": f"daily-{day.isoformat()}", "type": "daily", "related": []}, f"# {day.isoformat()}\n\n## 流水\n")
                self.save(doc, "创建每日日志", "system")
                return self.parse(path)
            except UnicodeDecodeError:
                repair = getattr(self.storage, "repair_utf8", None)
                if not repair:
                    raise
                repair(path)
                return self.parse(path)

    def append_daily(self, text: str, source: str = "对话", inferred: bool = False) -> None:
        with self._write_lock:
            doc = self.ensure_daily()
            marker = " (推测)" if inferred else ""
            stamp = datetime.now().strftime("%H:%M")
            doc.body = doc.body.rstrip() + f"\n- {stamp} {text}{marker} (来源: {date.today().isoformat()} {source})\n"
            self.save(doc, "记录新事件")

    def upsert_fact(self, path: str, section: str, fact: str, source: str, old_fact: Optional[str] = None, inferred: bool = False, condition: Optional[str] = None) -> None:
        with self._write_lock:
            doc = self.parse(path)
            line = fact.strip()
            if inferred and "(推测)" not in line:
                line += " (推测)"
            if condition and "(条件:" not in line:
                line += f" (条件: {condition})"
            if "(来源:" not in line:
                line += f" (来源: {source})"
            entry = "- " + line
            if old_fact:
                pattern = re.compile(r"^- .*" + re.escape(old_fact) + r".*$", re.M)
                if pattern.search(doc.body):
                    doc.body = pattern.sub(entry, doc.body, count=1)
                else:
                    doc.body = self._insert_section(doc.body, section, entry)
            elif entry not in doc.body:
                doc.body = self._insert_section(doc.body, section, entry)
            self.save(doc, f"更新事实：{fact}")

    @staticmethod
    def _insert_section(body: str, section: str, entry: str) -> str:
        heading = f"## {section}"
        if heading not in body:
            return body.rstrip() + f"\n\n{heading}\n\n{entry}\n"
        start = body.index(heading) + len(heading)
        next_heading = body.find("\n## ", start)
        insert_at = next_heading if next_heading >= 0 else len(body)
        return body[:insert_at].rstrip() + "\n" + entry + "\n\n" + body[insert_at:].lstrip("\n")

    def forget(self, phrase: str) -> int:
        if not phrase.strip():
            raise ValueError("忘记内容不能为空")
        changed = 0
        pattern = re.compile(r"^.*" + re.escape(phrase) + r".*(?:\n|$)", re.I | re.M)
        for path in list(self.storage.list(".md")):
            if path == "index.md":
                continue
            doc = self.parse(path)
            new_body, count = pattern.subn("", doc.body)
            if count:
                doc.body = new_body
                self.save(doc, f"按用户要求忘记：{phrase}", "user")
                changed += count
        self.upsert_fact("me.md", "禁止记录", f"不再记录：{phrase}", f"{date.today().isoformat()} 用户指令")
        self.rebuild_index()
        return changed

    def remove_chat_memory(self, chat_id: int) -> int:
        """Remove only memory lines tagged as originating from one chat exchange."""
        # Include the closing source marker so deleting #1 never matches #10.
        marker = f"对话 #{chat_id})"
        changed = 0
        for path in list(self.storage.list(".md")):
            if path == "index.md":
                continue
            doc = self.parse(path)
            lines = doc.body.splitlines()
            indexes = [index for index, line in enumerate(lines) if marker in line]
            if not indexes:
                continue
            remove: set[int] = set(indexes)
            if path.startswith("daily/"):
                for index in indexes:
                    start = index
                    while start >= 0 and not re.match(r"^- \d{2}:\d{2} 用户：", lines[start]):
                        start -= 1
                    if start >= 0:
                        remove.update(range(start, index + 1))
            doc.body = "\n".join(line for index, line in enumerate(lines) if index not in remove).rstrip() + "\n"
            self.save(doc, f"删除对话 #{chat_id} 的关联记忆", "user")
            changed += len(indexes)
        if changed:
            self.rebuild_index()
        return changed

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if term]
        results = []
        for path in self.storage.list(".md"):
            try:
                text = self.storage.read_text(path)
            except UnicodeDecodeError:
                # A damaged external import must not make all chat/search unavailable.
                continue
            score = sum(text.lower().count(term) for term in terms)
            if score:
                lines = [line for line in text.splitlines() if any(term in line.lower() for term in terms)]
                results.append({"path": path, "score": score, "excerpt": "\n".join(lines[:4])})
        return sorted(results, key=lambda item: (-item["score"], item["path"]))[:limit]

    def rebuild_index(self) -> None:
        rows = []
        for path in self.storage.list(".md"):
            if path == "index.md":
                continue
            doc = self.parse(path)
            summary = next((line.lstrip("# ").strip() for line in doc.body.splitlines() if line.strip()), "无摘要")
            rows.append(f"- [{path}]({path}) — {summary}")
        doc = MemoryDocument("index.md", {"id": "index", "type": "index", "related": []}, "# 记忆索引\n\n> 此文件自动生成，请勿手改。\n\n" + "\n".join(rows) + "\n")
        self.save(doc, "重建记忆索引", "system")

    def undo(self, mutation_id: int) -> None:
        rows = self.database.rows("SELECT * FROM mutations WHERE id=?", (mutation_id,))
        if not rows:
            raise KeyError("修改记录不存在")
        row = rows[0]
        self.storage.write_text(row["path"], row["before_text"])
        self.database.record_mutation(row["path"], row["after_text"], row["before_text"], f"撤销 #{mutation_id}", "user")
