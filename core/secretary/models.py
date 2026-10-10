from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .database import Database


@dataclass
class Route:
    task: str
    provider: str
    model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None


class ModelRouter:
    TASKS = ("fast", "smart", "vision", "video", "transcribe")

    def __init__(self, database: Database):
        self.database = database

    def providers(self) -> list[dict]:
        rows = self.database.rows("SELECT id,name,base_url,models,kind FROM providers ORDER BY name")
        for row in rows:
            row["models"] = json.loads(row["models"])
        return rows

    def save_provider(self, name: str, base_url: str, api_key: str, models: list[str], kind: str = "openai") -> None:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO providers(name,base_url,api_key,models,kind) VALUES(?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,api_key=excluded.api_key,models=excluded.models,kind=excluded.kind",
                (name, base_url.rstrip("/"), api_key, json.dumps(models, ensure_ascii=False), kind),
            )

    def set_route(self, route: Route) -> None:
        if route.task not in self.TASKS:
            raise ValueError("未知任务类型")
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO model_routes(task,provider,model,fallback_provider,fallback_model) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task) DO UPDATE SET provider=excluded.provider,model=excluded.model,fallback_provider=excluded.fallback_provider,fallback_model=excluded.fallback_model",
                (route.task, route.provider, route.model, route.fallback_provider, route.fallback_model),
            )

    def route(self, task: str) -> Optional[Route]:
        rows = self.database.rows("SELECT * FROM model_routes WHERE task=?", (task,))
        return Route(**rows[0]) if rows else None

    def complete(self, task: str, messages: list[dict], temperature: float = 0.2) -> str:
        route = self.route(task)
        if not route:
            raise RuntimeError(f"尚未配置 {task} 模型")
        attempts = [(route.provider, route.model)]
        if route.fallback_provider and route.fallback_model:
            attempts.append((route.fallback_provider, route.fallback_model))
        last_error = ""
        for provider_name, model in attempts:
            try:
                return self._openai_call(task, provider_name, model, messages, temperature)
            except Exception as exc:  # retry once, then route fallback
                last_error = str(exc)
                try:
                    return self._openai_call(task, provider_name, model, messages, temperature)
                except Exception as retry_exc:
                    last_error = str(retry_exc)
        raise RuntimeError(f"模型调用失败：{last_error}")

    def _openai_call(self, task: str, provider_name: str, model: str, messages: list[dict], temperature: float) -> str:
        with self.database.connect() as db:
            provider = db.execute("SELECT * FROM providers WHERE name=?", (provider_name,)).fetchone()
        if not provider:
            raise RuntimeError(f"供应商不存在：{provider_name}")
        payload = json.dumps({"model": model, "messages": messages, "temperature": temperature}).encode()
        request = urllib.request.Request(
            provider["base_url"].rstrip("/") + "/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {provider['api_key']}"},
        )
        status, error, prompt_tokens, completion_tokens, cost = "ok", None, 0, 0, 0.0
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read())
            usage = result.get("usage", {})
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
            return result["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, ValueError) as exc:
            status, error = "error", str(exc)
            raise
        finally:
            with self.database.connect() as db:
                db.execute(
                    "INSERT INTO ai_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,estimated_cost,status,error) VALUES(?,?,?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), task, provider_name, model, prompt_tokens, completion_tokens, cost, status, error),
                )


PROVIDER_TEMPLATES = {
    "OpenAI": "https://api.openai.com/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "通义千问": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "Kimi": "https://api.moonshot.cn/v1",
    "智谱": "https://open.bigmodel.cn/api/paas/v4",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "Ollama": "http://localhost:11434/v1",
}
