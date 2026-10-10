from __future__ import annotations

import json
import base64
import io
import mimetypes
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
        rows = self.database.rows("SELECT id,name,base_url,models,kind,consumption_level FROM providers ORDER BY name")
        for row in rows:
            row["models"] = json.loads(row["models"])
        return rows

    def save_provider(self, name: str, base_url: str, api_key: str, models: list[str], kind: str = "openai", consumption_level: str = "medium") -> None:
        if consumption_level not in {"low", "medium", "high"}:
            raise ValueError("消耗程度必须是 low、medium 或 high")
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO providers(name,base_url,api_key,models,kind,consumption_level) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,api_key=CASE WHEN excluded.api_key='' THEN providers.api_key ELSE excluded.api_key END,models=excluded.models,kind=excluded.kind,consumption_level=excluded.consumption_level",
                (name, base_url.rstrip("/"), api_key, json.dumps(models, ensure_ascii=False), kind, consumption_level),
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

    def delete_provider(self, provider_id: int) -> Optional[str]:
        with self.database.connect() as db:
            row = db.execute("SELECT name FROM providers WHERE id=?", (provider_id,)).fetchone()
            if not row:
                return None
            name = row["name"]
            db.execute("DELETE FROM model_routes WHERE provider=?", (name,))
            db.execute("UPDATE model_routes SET fallback_provider=NULL,fallback_model=NULL WHERE fallback_provider=?", (name,))
            db.execute("DELETE FROM providers WHERE id=?", (provider_id,))
        return name

    def route(self, task: str) -> Optional[Route]:
        rows = self.database.rows("SELECT * FROM model_routes WHERE task=?", (task,))
        return Route(**rows[0]) if rows else None

    def complete(self, task: str, messages: list[dict], temperature: float = 0.2, provider: Optional[str] = None, model: Optional[str] = None) -> str:
        route = self.route(task)
        if provider or model:
            if not provider or not model:
                raise ValueError("临时模型必须同时指定供应商和模型")
            attempts = [(provider, model)]
        else:
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

    def analyze_images(self, task: str, paths: list, prompt: str, provider: Optional[str] = None, model: Optional[str] = None) -> str:
        content = [{"type": "text", "text": prompt}]
        for path in paths:
            raw, mime = self._image_payload(path)
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}", "detail": "auto"}})
        return self.complete(task, [{"role": "user", "content": content}], provider=provider, model=model)

    @staticmethod
    def _image_payload(path) -> tuple[bytes, str]:
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1600, 1600))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=86, optimize=True)
                return output.getvalue(), "image/jpeg"
        except ImportError:
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"

    def _openai_call(self, task: str, provider_name: str, model: str, messages: list[dict], temperature: float) -> str:
        with self.database.connect() as db:
            provider = db.execute("SELECT * FROM providers WHERE name=?", (provider_name,)).fetchone()
        if not provider:
            raise RuntimeError(f"供应商不存在：{provider_name}")
        token_budgets = {"low": 512, "medium": 1024, "high": 2048}
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": token_budgets.get(provider["consumption_level"], 1024),
        }).encode()
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
            content = result["choices"][0]["message"].get("content")
            if isinstance(content, list):
                content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("text"))
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型返回了空内容，请更换模型或降低消耗程度后重试")
            return content.strip()
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
