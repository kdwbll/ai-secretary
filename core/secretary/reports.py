from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .database import Database
from .memory import MemoryEngine


class ReportService:
    def __init__(self, memory: MemoryEngine, database: Database, notify=None):
        self.memory, self.database = memory, database
        self.notify = notify

    def morning(self) -> str:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        daily = self.memory.ensure_daily(today)
        events = self.database.rows("SELECT kind,payload FROM events WHERE created_at >= ? ORDER BY id DESC LIMIT 20", (today.isoformat(),))
        pickups = [e for e in events if e["kind"] == "pickup"]
        lines = [f"# {today.isoformat()} 早报", "", "## 今天最重要的事", "- 先完成一个最关键且有截止时间的动作。"]
        if pickups:
            lines += ["", "## 待办提醒", f"- 有 {len(pickups)} 个快递待取，请查看今日流水中的取件码。"]
        projects = self.memory.storage.list(".md")
        project_count = sum(path.startswith("projects/") for path in projects)
        if project_count:
            lines += ["", "## 项目", f"- 你有 {project_count} 个项目档案，今天推进其中最重要的一步。"]
        content = "\n".join(lines)
        self._save("morning", content)
        return content

    def evening(self) -> str:
        doc = self.memory.ensure_daily()
        expense = re.findall(r"支出 ¥([\d.]+)", doc.body)
        guesses = [line for line in doc.body.splitlines() if "(推测)" in line]
        total = sum(float(value) for value in expense)
        content = f"# 今晚复盘\n\n今天记录支出 ¥{total:.2f}，共有 {len(guesses)} 条待确认推测。"
        if guesses:
            content += "\n\n## 待确认\n" + "\n".join(guesses)
        self._save("evening", content)
        return content

    def weekly(self) -> str:
        changed = []
        for path in self.memory.storage.list(".md"):
            if path == "index.md":
                continue
            doc = self.memory.parse(path)
            seen, lines = set(), []
            for line in doc.body.splitlines():
                key = re.sub(r"\s*\(来源:.*?\)\s*$", "", line).strip()
                if key and key in seen and line.startswith("- "):
                    changed.append(f"{path}: 合并重复条目 {key}")
                    continue
                if key:
                    seen.add(key)
                lines.append(line)
            new_body = "\n".join(lines).rstrip() + "\n"
            if new_body != doc.body:
                doc.body = new_body
                self.memory.save(doc, "每周整理：合并重复")
        self.memory.rebuild_index()
        content = "# 每周整理报告\n\n" + ("\n".join(f"- {item}" for item in changed) if changed else "- 未发现需要合并的重复内容。")
        self._save("weekly", content)
        return content

    def _save(self, kind: str, content: str) -> None:
        with self.database.connect() as db:
            created_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
            db.execute("INSERT INTO reports(created_at,kind,content) VALUES(?,?,?)", (created_at, kind, content))
        if self.notify:
            titles = {"morning": "第二大脑早报", "evening": "今晚复盘", "weekly": "每周整理"}
            self.notify(kind, titles.get(kind, "第二大脑"), content)
