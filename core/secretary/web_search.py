from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .database import Database


@dataclass
class SearchOutcome:
    results: list[dict[str, str]] = field(default_factory=list)
    error: str = ""
    provider: str = ""


class WebSearchService:
    """Optional, query-scoped web search for the assistant.

    Search snippets are treated as untrusted external data and are never
    executed. Credentials stay server-side in SecretStore ciphertext.
    """

    def __init__(self, database: Database, secret_store):
        self.database = database
        self.secret_store = secret_store

    def search(self, query: str, category: str = "web", limit: int = 6) -> SearchOutcome:
        if self.database.setting("web_search_enabled", "0") != "1":
            return SearchOutcome(error="联网搜索未开启。请在设置页启用后再试。")
        provider = self.database.setting("web_search_provider", "brave") or "brave"
        try:
            if provider == "brave":
                return self._brave(query, category, limit)
            if provider == "searxng":
                return self._searxng(query, category, limit)
            return SearchOutcome(error="联网搜索供应商配置无效。", provider=provider)
        except HTTPError as exc:
            if exc.code == 401:
                message = "联网搜索鉴权失败，请检查搜索 API Key。"
            elif exc.code == 429:
                message = "联网搜索请求过多或额度已用完，请稍后重试。"
            else:
                message = f"联网搜索服务返回错误（HTTP {exc.code}）。"
            return SearchOutcome(error=message, provider=provider)
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return SearchOutcome(error="联网搜索失败，请检查电脑网络与搜索服务设置。", provider=provider)

    def _brave(self, query: str, category: str, limit: int) -> SearchOutcome:
        encrypted = self.database.setting("web_search_api_key", "") or ""
        if not encrypted:
            return SearchOutcome(error="尚未填写 Brave Search API Key。", provider="brave")
        key = self.secret_store.decrypt(encrypted)
        endpoint = "https://api.search.brave.com/res/v1/news/search" if category == "news" else "https://api.search.brave.com/res/v1/web/search"
        params = {
            "q": query[:600], "count": max(1, min(limit, 10)), "country": "CN",
            "search_lang": "zh-hans", "ui_lang": "zh-CN", "safesearch": "moderate",
        }
        if category == "news":
            params["freshness"] = "pw"
        request = Request(
            endpoint + "?" + urlencode(params),
            headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": "SecondBrain/0.7.4"},
        )
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        container = payload.get("results") if category == "news" else (payload.get("web") or {}).get("results")
        return SearchOutcome(results=self._normalize(container or [], limit), provider="brave")

    def _searxng(self, query: str, category: str, limit: int) -> SearchOutcome:
        base = (self.database.setting("searxng_url", "") or "").strip()
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return SearchOutcome(error="请填写完整的 SearXNG 地址，例如 http://127.0.0.1:8080。", provider="searxng")
        endpoint = base.rstrip("/")
        if not endpoint.endswith("/search"):
            endpoint += "/search"
        params = {
            "q": query[:600], "format": "json", "language": "zh-CN", "safesearch": 1,
            "categories": "news" if category == "news" else "general",
        }
        request = Request(endpoint + "?" + urlencode(params), headers={"Accept": "application/json", "User-Agent": "SecondBrain/0.7.4"})
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        return SearchOutcome(results=self._normalize(payload.get("results") or [], limit), provider="searxng")

    @staticmethod
    def _normalize(items: list[dict], limit: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
                continue
            title = WebSearchService._plain(item.get("title") or parsed.netloc)
            snippet = WebSearchService._plain(item.get("description") or item.get("content") or "")
            results.append({
                "title": title[:300], "url": url[:2000], "snippet": snippet[:1200],
                "age": str(item.get("age") or item.get("published") or item.get("publishedDate") or "")[:80],
            })
            seen.add(url)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _plain(value) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(value)))).strip()
