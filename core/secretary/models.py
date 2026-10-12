from __future__ import annotations

import json
import base64
import io
import mimetypes
import re
import urllib.error
import urllib.request
import socket
import time
import random
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional

from .database import Database
from .secrets import SecretStore


class ModelError(RuntimeError):
    code = "provider_error"
    user_message = "模型服务暂时不可用，请稍后重试"
    retryable = True


class ModelNotConfiguredError(ModelError):
    code = "model_not_configured"
    user_message = "尚未配置文字模型，请先到设置页添加供应商并选择文字处理模型"
    retryable = False


class ModelNetworkError(ModelError):
    code = "network_error"
    user_message = "无法连接模型服务，请检查网络和接口地址后重试"


class ModelRateLimitError(ModelError):
    code = "rate_limited"
    user_message = "模型请求过于频繁或额度已用尽，请稍后重试或更换模型"

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ModelResponseError(ModelError):
    code = "invalid_response"
    user_message = "模型返回内容异常，请更换模型或稍后重试"
    retryable = False


@dataclass
class Route:
    task: str
    provider: str
    model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None


class ModelRouter:
    TASKS = ("fast", "smart", "vision", "video", "transcribe")

    def __init__(self, database: Database, secrets: Optional[SecretStore] = None):
        self.database = database
        self.secrets = secrets or SecretStore(database.path.parent / ".secrets-key")
        self.secrets.migrate_database(database)

    def providers(self) -> list[dict]:
        self.seed_known_prices()
        rows = self.database.rows("SELECT id,name,base_url,models,kind,consumption_level FROM providers ORDER BY name")
        prices = {(row["provider"], row["model"]): row for row in self.database.rows("SELECT provider,model,input_per_million,output_per_million,currency,updated_at FROM model_prices")}
        for row in rows:
            row["models"] = json.loads(row["models"])
            row["prices"] = {model: prices.get((row["name"], model)) for model in row["models"]}
        return rows

    def seed_known_prices(self) -> None:
        providers = self.database.rows("SELECT name,base_url,models FROM providers")
        defaults = []
        for provider in providers:
            for model in json.loads(provider["models"]):
                normalized = model.lower().replace("_", "-")
                if normalized == "deepseek-flash" and "deepseek.com" in provider["base_url"]:
                    defaults.append((provider["name"], model, 0.30, 1.20, "USD"))
                elif normalized.startswith("doubao-seed-2-1-lite"):
                    defaults.append((provider["name"], model, 1.60, 5.40, "CNY"))
        if not defaults:
            return
        with self.database.connect() as db:
            for provider, model, input_price, output_price, currency in defaults:
                db.execute(
                    "INSERT OR IGNORE INTO model_prices(provider,model,input_per_million,output_per_million,currency,updated_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                    (provider, model, input_price, output_price, currency),
                )
        self.recalculate_costs()

    def save_price(self, provider: str, model: str, input_per_million: float, output_per_million: float, currency: str) -> None:
        currency = currency.upper()
        if input_per_million < 0 or output_per_million < 0:
            raise ValueError("模型单价不能小于 0")
        if currency not in {"CNY", "USD"}:
            raise ValueError("币种只支持 CNY 或 USD")
        if not self.database.rows("SELECT 1 FROM providers WHERE name=?", (provider,)):
            raise ValueError("供应商不存在")
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO model_prices(provider,model,input_per_million,output_per_million,currency,updated_at) VALUES(?,?,?,?,?,datetime('now','localtime')) "
                "ON CONFLICT(provider,model) DO UPDATE SET input_per_million=excluded.input_per_million,output_per_million=excluded.output_per_million,currency=excluded.currency,updated_at=excluded.updated_at",
                (provider, model, input_per_million, output_per_million, currency),
            )
        self.recalculate_costs(provider, model)

    def set_usd_cny_rate(self, rate: float) -> None:
        if not 1 <= rate <= 20:
            raise ValueError("美元兑人民币汇率应在 1 到 20 之间")
        self.database.set_setting("usd_cny_rate", str(rate))
        self.recalculate_costs()

    def _cost_cny(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        prices = self.database.rows("SELECT * FROM model_prices WHERE provider=? AND model=?", (provider, model))
        if not prices:
            return 0.0
        price = prices[0]
        native = (prompt_tokens * float(price["input_per_million"]) + completion_tokens * float(price["output_per_million"])) / 1_000_000
        rate = float(self.database.setting("usd_cny_rate", "7.20") or 7.20) if price["currency"] == "USD" else 1.0
        return native * rate

    def recalculate_costs(self, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        clauses, params = [], []
        if provider is not None:
            clauses.append("provider=?")
            params.append(provider)
        if model is not None:
            clauses.append("model=?")
            params.append(model)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.database.rows("SELECT id,provider,model,prompt_tokens,completion_tokens FROM ai_calls" + where, tuple(params))
        with self.database.connect() as db:
            for row in rows:
                cost = self._cost_cny(row["provider"], row["model"], row["prompt_tokens"], row["completion_tokens"])
                db.execute("UPDATE ai_calls SET estimated_cost=? WHERE id=?", (cost, row["id"]))

    def save_provider(self, name: str, base_url: str, api_key: str, models: list[str], kind: str = "openai", consumption_level: str = "medium") -> None:
        if consumption_level not in {"low", "medium", "high"}:
            raise ValueError("消耗程度必须是 low、medium 或 high")
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO providers(name,base_url,api_key,models,kind,consumption_level) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,api_key=CASE WHEN excluded.api_key='' THEN providers.api_key ELSE excluded.api_key END,models=excluded.models,kind=excluded.kind,consumption_level=excluded.consumption_level",
                (name, base_url.rstrip("/"), self.secrets.encrypt(api_key), json.dumps(models, ensure_ascii=False), kind, consumption_level),
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
                raise ModelNotConfiguredError(f"尚未配置 {task} 模型")
            attempts = [(route.provider, route.model)]
            if route.fallback_provider and route.fallback_model:
                attempts.append((route.fallback_provider, route.fallback_model))
        last_exception: Exception = ModelError("模型调用失败")
        for provider_name, model in attempts:
            for retry_index in range(3):
                try:
                    return self._openai_call(task, provider_name, model, messages, temperature)
                except ModelNotConfiguredError:
                    raise
                except Exception as exc:
                    classified = self._classify_error(exc)
                    last_exception = classified
                    if not classified.retryable:
                        raise classified from exc
                    if retry_index < 2:
                        if self._sleep_before_retry(classified, retry_index):
                            continue
                    break
        raise last_exception

    def stream_complete(self, task: str, messages: list[dict], temperature: float = 0.2,
                        provider: Optional[str] = None, model: Optional[str] = None) -> Iterator[str]:
        route = self.route(task)
        if provider or model:
            if not provider or not model:
                raise ValueError("临时模型必须同时指定供应商和模型")
            attempts = [(provider, model)]
        elif route:
            attempts = [(route.provider, route.model)]
            if route.fallback_provider and route.fallback_model:
                attempts.append((route.fallback_provider, route.fallback_model))
        else:
            raise ModelNotConfiguredError(f"尚未配置 {task} 模型")

        last_error: Exception = ModelError("模型调用失败")
        for provider_name, selected_model in attempts:
            for retry_index in range(3):
                emitted = False
                try:
                    for chunk in self._openai_stream(task, provider_name, selected_model, messages, temperature):
                        emitted = True
                        yield chunk
                    return
                except Exception as exc:
                    classified = self._classify_error(exc)
                    if emitted or not classified.retryable:
                        raise classified from exc
                    last_error = classified
                    if retry_index < 2:
                        if self._sleep_before_retry(classified, retry_index):
                            continue
                    break
        raise last_error

    @staticmethod
    def _sleep_before_retry(error: ModelError, retry_index: int) -> bool:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            # A long server cooldown must not be shortened. Let the caller
            # return the failure or use its fallback instead of blocking.
            if float(retry_after) > 10.0:
                return False
            delay = max(0.5, float(retry_after))
        else:
            base = 1.0 if isinstance(error, ModelRateLimitError) else 0.5
            delay = min(base * (2 ** retry_index), 8.0) + random.uniform(0, base * 0.5)
        time.sleep(delay)
        return True

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
        level = provider["consumption_level"]
        token_budgets = {"low": 2048, "medium": 4096, "high": 8192}
        segment_limits = {"low": 1, "medium": 2, "high": 3}
        max_tokens = token_budgets.get(level, 4096)
        status, error, prompt_tokens, completion_tokens, cost = "ok", None, 0, 0, 0.0
        try:
            conversation = list(messages)
            parts = []
            truncated = False
            for _ in range(segment_limits.get(level, 2)):
                payload = json.dumps({"model": model, "messages": conversation, "temperature": temperature, "max_tokens": max_tokens}).encode()
                request = urllib.request.Request(
                    provider["base_url"].rstrip("/") + "/chat/completions",
                    data=payload,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.secrets.decrypt(provider['api_key'])}"},
                )
                with urllib.request.urlopen(request, timeout=90) as response:
                    result = json.loads(response.read())
                usage = result.get("usage", {})
                choice = result["choices"][0]
                content = choice["message"].get("content")
                if isinstance(content, list):
                    content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("text"))
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("模型返回了空内容，请更换模型或调整消耗程度后重试")
                upstream_prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
                upstream_completion = usage.get("completion_tokens", usage.get("output_tokens"))
                prompt_value = int(upstream_prompt or 0)
                completion_value = int(upstream_completion or 0)
                prompt_tokens += prompt_value if prompt_value > 0 else self._estimate_tokens(conversation)
                completion_tokens += completion_value if completion_value > 0 else self._estimate_tokens(content)
                parts.append(content.strip())
                truncated = choice.get("finish_reason") == "length"
                if not truncated:
                    break
                conversation = list(messages) + [
                    {"role": "assistant", "content": "\n\n".join(parts)},
                    {"role": "user", "content": "上一段回答因长度限制被截断。请从断点处直接继续，不要重复已经写过的内容，并完整收尾。"},
                ]
            answer = "\n\n".join(parts)
            if truncated:
                level_label = {"low": "小", "medium": "中", "high": "大"}.get(level, "中")
                answer += f"\n\n（回答达到“{level_label}消耗”上限；如需更详细内容，可提高该供应商的消耗程度后继续提问。）"
            return answer
        except Exception as exc:
            status, error = "error", str(exc)
            if isinstance(exc, ValueError):
                raise
            raise self._classify_error(exc) from exc
        finally:
            cost = self._cost_cny(provider_name, model, prompt_tokens, completion_tokens)
            with self.database.connect() as db:
                db.execute(
                    "INSERT INTO ai_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,estimated_cost,status,error) VALUES(?,?,?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), task, provider_name, model, prompt_tokens, completion_tokens, cost, status, error),
                )

    def _openai_stream(self, task: str, provider_name: str, model: str, messages: list[dict], temperature: float) -> Iterator[str]:
        rows = self.database.rows("SELECT * FROM providers WHERE name=?", (provider_name,))
        if not rows:
            raise ModelNotConfiguredError(f"供应商不存在：{provider_name}")
        provider = rows[0]
        max_tokens = {"low": 2048, "medium": 4096, "high": 8192}.get(provider["consumption_level"], 4096)
        prompt_tokens = 0
        completion_tokens = 0
        status, error = "ok", None
        try:
            payload = json.dumps({
                "model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, "stream": True,
                "stream_options": {"include_usage": True},
            }).encode()
            request = urllib.request.Request(
                provider["base_url"].rstrip("/") + "/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.secrets.decrypt(provider['api_key'])}"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                prompt_tokens = self._estimate_tokens(messages)
                received_content, finished = False, False
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    event = json.loads(data)
                    usage = event.get("usage") or {}
                    if usage:
                        prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", prompt_tokens)) or prompt_tokens)
                        completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", completion_tokens)) or completion_tokens)
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    if choices[0].get("finish_reason"):
                        finished = True
                    delta = choices[0].get("delta", {}).get("content", "")
                    if isinstance(delta, list):
                        delta = "".join(str(item.get("text", "")) for item in delta if isinstance(item, dict))
                    if delta:
                        received_content = True
                        completion_tokens += self._estimate_tokens(delta) if not usage else 0
                        yield str(delta)
                if not received_content or not finished:
                    raise ModelNetworkError("模型流在完整回答前断开")
        except Exception as exc:
            status, error = "error", str(exc)
            raise self._classify_error(exc) from exc
        finally:
            cost = self._cost_cny(provider_name, model, prompt_tokens, completion_tokens)
            with self.database.connect() as db:
                db.execute(
                    "INSERT INTO ai_calls(created_at,task,provider,model,prompt_tokens,completion_tokens,estimated_cost,status,error) VALUES(?,?,?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), task, provider_name, model, prompt_tokens, completion_tokens, cost, status, error),
                )

    @staticmethod
    def _classify_error(exc: Exception) -> ModelError:
        if isinstance(exc, ModelError):
            return exc
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code == 429 or 500 <= exc.code <= 599:
                retry_after = None
                try:
                    raw = exc.headers.get("Retry-After") if exc.headers else None
                    if raw:
                        try:
                            retry_after = float(raw)
                        except ValueError:
                            retry_after = max(0, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError):
                    pass
                error = ModelRateLimitError(str(exc), retry_after) if exc.code == 429 else ModelError(str(exc))
                error.retry_after = retry_after
                return error
            if exc.code in {401, 403}:
                error = ModelError("模型密钥无效或没有权限")
                error.user_message = "模型密钥无效或没有权限，请到设置页检查 API Key"
                error.retryable = False
                return error
            if 400 <= exc.code <= 499 and exc.code != 408:
                error = ModelResponseError(str(exc))
                error.user_message = "模型请求参数不被支持，请检查接口地址与模型设置"
                return error
        if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError)):
            return ModelNetworkError(str(exc))
        if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)):
            return ModelResponseError(str(exc))
        return ModelError(str(exc))

    @classmethod
    def _estimate_tokens(cls, value) -> int:
        """Estimate usage only when an OpenAI-compatible provider omits usage data."""
        if value is None:
            return 0
        if isinstance(value, str):
            if value.startswith("data:") and ";base64," in value[:100]:
                return 0
            cjk = len(re.findall(r"[\u3400-\u9fff]", value))
            other = len(re.sub(r"\s|[\u3400-\u9fff]", "", value))
            return max(1, round(cjk * 0.8 + other / 4)) if value.strip() else 0
        if isinstance(value, dict):
            return sum(cls._estimate_tokens(item) for item in value.values()) + 3
        if isinstance(value, (list, tuple)):
            return sum(cls._estimate_tokens(item) for item in value)
        return cls._estimate_tokens(str(value))


PROVIDER_TEMPLATES = {
    "OpenAI": "https://api.openai.com/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "通义千问": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "Kimi": "https://api.moonshot.cn/v1",
    "智谱": "https://open.bigmodel.cn/api/paas/v4",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "Ollama": "http://localhost:11434/v1",
}
