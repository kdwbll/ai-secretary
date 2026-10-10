from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from .database import Database
from .memory import MemoryEngine
from .models import ModelRouter
from .parsers import ParsedEvent, parse_notification, parse_sms


DOMAIN_HINTS = {
    "health.md": ("健康", "睡眠", "体重", "心率", "医院", "过敏", "药"),
    "finance.md": ("花", "钱", "收入", "工资", "预算", "消费", "账单", "元"),
    "habits.md": ("习惯", "每天", "经常", "作息", "起床", "运动", "饮食"),
    "work-study.md": ("工作", "学习", "考试", "项目", "截止", "任务"),
    "interests.md": ("喜欢", "兴趣", "电影", "音乐", "游戏", "旅行"),
    "me.md": ("我是", "目标", "价值观", "不要", "偏好"),
}


class SecretaryService:
    def __init__(self, memory: MemoryEngine, database: Database, models: ModelRouter, prompt_dir: Path):
        self.memory, self.database, self.models, self.prompt_dir = memory, database, models, prompt_dir

    def initialize(self) -> None:
        self.memory.initialize()

    def choose_context(self, message: str, limit: int = 5) -> list[str]:
        scored = []
        for path, hints in DOMAIN_HINTS.items():
            score = sum(1 for hint in hints if hint in message)
            if score:
                scored.append((score, path))
        for hit in self.memory.search(message, limit):
            scored.append((hit["score"], hit["path"]))
        chosen = []
        for _, path in sorted(scored, reverse=True):
            if path not in chosen and path != "index.md":
                chosen.append(path)
        return chosen[:limit] or ["me.md", "work-study.md"]

    def _context(self, message: str) -> str:
        limit = int(self.database.setting("max_context_files", "5") or 5)
        paths = self.choose_context(message, limit)
        for offset in range(3):
            daily = f"daily/{(date.today() - timedelta(days=offset)).isoformat()}.md"
            if daily in set(self.memory.storage.list(".md")):
                paths.append(daily)
        return "\n\n".join(f"## {path}\n{self.memory.storage.read_text(path)}" for path in dict.fromkeys(paths))

    def chat(self, message: str) -> dict[str, Any]:
        message = message.strip()
        forget = re.match(r"^(?:请)?忘掉|^(?:请)?忘记", message)
        if forget:
            phrase = re.sub(r"^(?:请)?(?:忘掉|忘记)\s*", "", message).strip("。！! ")
            count = self.memory.forget(phrase)
            return {"answer": f"已从记忆中删除与“{phrase}”有关的 {count} 条内容，并加入禁止记录规则。", "sources": ["me.md"]}

        context = self._context(message)
        paths = self.choose_context(message, int(self.database.setting("max_context_files", "5") or 5))
        try:
            system = (self.prompt_dir / "chat.md").read_text(encoding="utf-8")
            answer = self.models.complete("smart", [{"role": "system", "content": system + "\n\n用户记忆：\n" + context}, {"role": "user", "content": message}])
        except RuntimeError:
            answer = self._local_answer(message, context, paths)
        self.memory.append_daily(f"用户：{message}\n  - 助理：{answer}", "对话")
        self._extract_local_fact(message)
        self.memory.rebuild_index()
        return {"answer": answer, "sources": paths}

    def _local_answer(self, message: str, context: str, paths: list[str]) -> str:
        facts = [line[2:] for line in context.splitlines() if line.startswith("- ")][:5]
        basis = "；".join(facts) if facts else "目前记忆信息还很少"
        return f"我已结合你的本地记忆分析。{basis}。针对“{message}”，建议先明确最迟完成时间与下一步动作，再把下一步安排到今天；如果你补充限制条件，我可以继续细化。"

    def _extract_local_fact(self, message: str) -> None:
        if len(message) < 4 or message.endswith("?") or message.endswith("？"):
            return
        best = max(DOMAIN_HINTS.items(), key=lambda item: sum(h in message for h in item[1]))
        if sum(h in message for h in best[1]) == 0:
            return
        repeated = any(word in message for word in ("每天", "经常", "通常", "习惯"))
        section = {"health.md": "当前状况", "finance.md": "收支与预算", "habits.md": "作息", "work-study.md": "当前事项", "interests.md": "兴趣与娱乐", "me.md": "基本信息"}[best[0]]
        self.memory.upsert_fact(best[0], section, message.rstrip("。"), f"{date.today().isoformat()} 对话", inferred=not repeated and best[0] == "habits.md")

    def ingest_sms(self, text: str, sender: str = "") -> dict:
        event = parse_sms(text, sender)
        self._apply_event(event, "短信")
        self.database.add_event("sms", event.kind, event.to_dict())
        return event.to_dict()

    def ingest_notification(self, package: str, title: str, text: str) -> dict:
        event = parse_notification(package, title, text)
        self._apply_event(event, "通知")
        self.database.add_event("notification", event.kind, event.to_dict())
        return event.to_dict()

    def _apply_event(self, event: ParsedEvent, source: str) -> None:
        if event.ignored:
            return
        self.memory.append_daily(event.raw or event.title, source, inferred=event.kind == "unknown")
        if event.kind == "expense" and event.amount is not None:
            detail = f"{date.today().isoformat()} 支出 ¥{event.amount:.2f}"
            if event.merchant:
                detail += f"，商户 {event.merchant}"
            self.memory.upsert_fact("finance.md", "近期流水", detail, f"{date.today().isoformat()} {source}")
        elif event.kind == "health_appointment":
            self.memory.upsert_fact("health.md", "当前状况", event.raw, f"{date.today().isoformat()} {source}")

    def interview_questions(self) -> list[dict[str, str]]:
        return [
            {"domain": "基本信息", "question": "我该怎么称呼你？你目前生活在哪座城市？"},
            {"domain": "生活习惯", "question": "你通常几点睡、几点起？最想改善哪个习惯？"},
            {"domain": "健康", "question": "有哪些疾病、过敏或健康目标需要我始终记住？"},
            {"domain": "财务", "question": "你目前最重要的预算规则或储蓄目标是什么？"},
            {"domain": "人际", "question": "有哪些重要的人和日期需要我提醒？"},
            {"domain": "工作学习", "question": "你目前最重要的工作或学习目标是什么？"},
            {"domain": "兴趣与目标", "question": "你喜欢什么？未来一年最想完成哪件事？"},
        ]
