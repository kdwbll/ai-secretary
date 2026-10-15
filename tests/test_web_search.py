import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from unittest.mock import Mock

from core.secretary.database import Database
from core.secretary.secrets import SecretStore
from core.secretary.service import SecretaryService
from core.secretary.web_search import SearchOutcome, WebSearchService


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.payload[:limit] if limit >= 0 else self.payload


class WebSearchTests(TestCase):
    def test_bocha_results_are_normalized_and_key_stays_in_header(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data.db")
            secrets = SecretStore(root / ".key")
            database.set_setting("web_search_enabled", "1")
            database.set_setting("web_search_provider", "bocha")
            database.set_setting("bocha_search_api_key", secrets.encrypt("secret-search-key"))
            service = WebSearchService(database, secrets)
            payload = {"webPages": {"value": [{
                "name": "<b>示例商品</b>", "url": "https://example.com/item",
                "summary": "<p>当前参考价格 99 元</p>", "siteName": "示例网站",
                "datePublished": "2026-10-12T10:00:00+08:00",
            }]}}
            with patch("core.secretary.web_search.urlopen", return_value=_Response(payload)) as mocked:
                outcome = service.search("示例商品多少钱")
            self.assertEqual(outcome.results[0]["title"], "示例商品")
            self.assertEqual(outcome.results[0]["snippet"], "当前参考价格 99 元")
            self.assertEqual(outcome.results[0]["site"], "示例网站")
            self.assertEqual(outcome.provider, "bocha")
            request = mocked.call_args.args[0]
            self.assertNotIn("secret-search-key", request.full_url)
            self.assertEqual(request.get_header("Authorization"), "Bearer secret-search-key")
            self.assertEqual(request.get_method(), "POST")
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["query"], "示例商品多少钱")
            self.assertTrue(body["summary"])

    def test_news_search_uses_recent_bocha_results_and_wrapped_payload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "data.db")
            secrets = SecretStore(root / ".key")
            database.set_setting("web_search_enabled", "1")
            database.set_setting("web_search_provider", "bocha")
            database.set_setting("bocha_search_api_key", secrets.encrypt("key"))
            payload = {"data": {"webPages": {"value": [{
                "name": "今日新闻", "url": "https://example.cn/news", "snippet": "新闻摘要",
            }]}}}
            with patch("core.secretary.web_search.urlopen", return_value=_Response(payload)) as mocked:
                outcome = WebSearchService(database, secrets).search("今日新闻", category="news")
            self.assertEqual(outcome.results[0]["title"], "今日新闻")
            self.assertEqual(json.loads(mocked.call_args.args[0].data.decode("utf-8"))["freshness"], "oneWeek")

    def test_search_is_only_triggered_for_web_dependent_questions(self):
        self.assertFalse(SecretaryService._web_search_candidate("我今天心情不错"))
        self.assertFalse(SecretaryService._web_search_candidate("帮我整理一下本周任务"))
        self.assertFalse(SecretaryService._web_search_candidate("我上个月花了多少钱"))
        self.assertFalse(SecretaryService._web_search_candidate("我今天花了多少钱"))
        self.assertFalse(SecretaryService._web_search_candidate("我设置了哪些目标"))
        self.assertTrue(SecretaryService._web_search_candidate("帮我搜索一下这个软件的官网"))
        self.assertTrue(SecretaryService._web_search_candidate("这款手机现在多少钱"))
        self.assertTrue(SecretaryService._web_search_candidate("今天有什么新闻"))

    def test_irrelevant_provider_results_are_removed_and_matches_rank_first(self):
        results = [
            {"title": "彩票中奖号码", "snippet": "今日开奖", "site": "论坛"},
            {"title": "成都天气预报", "snippet": "今天成都晴", "site": "气象服务"},
            {"title": "成都旅游攻略", "snippet": "景点推荐", "site": "旅行网"},
        ]
        ranked = WebSearchService._rank("帮我查一下成都天气", results, 5)
        self.assertEqual([item["title"] for item in ranked], ["成都天气预报"])
        self.assertNotIn("彩票中奖号码", [item["title"] for item in ranked])

    def test_external_results_are_marked_untrusted_and_require_sources(self):
        context = SecretaryService._web_search_context(SearchOutcome(results=[{
            "title": "新闻标题", "url": "https://example.com/news", "snippet": "摘要", "age": "今天",
        }], provider="brave"))
        self.assertIn("外部不可信数据", context)
        self.assertIn("Markdown 来源链接", context)
        self.assertIn("https://example.com/news", context)

    def test_nearby_restaurant_price_search_adds_deal_sources(self):
        search = Mock()
        search.search.return_value = SearchOutcome()
        service = object.__new__(SecretaryService)
        service.web_search = search
        service._web_search("最近的自助餐多少钱")
        query = search.search.call_args.args[0]
        self.assertIn("美团", query)
        self.assertIn("大众点评", query)
