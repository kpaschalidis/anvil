import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from scout.sources.hackernews import (
    HackerNewsSource,
    HackerNewsError,
    RateLimiter,
)
from scout.config import HackerNewsConfig
from scout.models import SearchTask, DocumentRef


class TestRateLimiter:
    def test_init_defaults(self):
        limiter = RateLimiter()
        assert limiter.requests_per_minute == 30
        assert limiter.min_delay == 0.5

    def test_init_custom(self):
        limiter = RateLimiter(requests_per_minute=60, min_delay=1.0)
        assert limiter.requests_per_minute == 60
        assert limiter.min_delay == 1.0

    def test_wait_increments_count(self):
        limiter = RateLimiter(min_delay=0.0)
        assert limiter.request_count == 0
        limiter.wait()
        assert limiter.request_count == 1


class TestHackerNewsConfig:
    def test_defaults(self):
        config = HackerNewsConfig()
        assert config.rate_limit_per_minute == 30
        assert config.request_delay_seconds == 0.5
        assert config.max_comments_per_story == 100
        assert config.comment_depth_limit == 5
        assert config.hits_per_page == 100


class TestHackerNewsSource:
    @pytest.fixture
    def source(self):
        config = HackerNewsConfig(
            rate_limit_per_minute=1000,
            request_delay_seconds=0.0,
        )
        return HackerNewsSource(config)

    def test_name(self, source):
        assert source.name == "hackernews"

    def test_discover_returns_entities(self, source):
        entities = source.discover("test topic")
        assert len(entities) == 5
        assert entities[0].entity_id == "hackernews:ask"
        assert entities[0].name == "ask"
        assert entities[0].display_name == "Ask HN"

    def test_discover_limit(self, source):
        entities = source.discover("test topic", limit=2)
        assert len(entities) == 2

    def test_adapt_queries(self, source):
        queries = ["CRM problems", "sales software"]
        tasks = source.adapt_queries(queries, "CRM pain points")

        assert len(tasks) == 4
        search_tasks = [t for t in tasks if t.mode == "search"]
        assert len(search_tasks) == 4
        
        all_queries = [t.query for t in tasks]
        assert "CRM problems" in all_queries
        assert "sales software" in all_queries


class TestAlgoliaSearch:
    @pytest.fixture
    def source(self):
        config = HackerNewsConfig(
            rate_limit_per_minute=1000,
            request_delay_seconds=0.0,
        )
        return HackerNewsSource(config)

    def test_parse_algolia_response(self, source):
        mock_response = {
            "hits": [
                {
                    "objectID": "12345",
                    "title": "Ask HN: Best CRM for startups?",
                    "author": "testuser",
                    "points": 150,
                    "num_comments": 89,
                },
                {
                    "objectID": "12346",
                    "title": "Show HN: New CRM tool",
                    "author": "builder",
                    "points": 50,
                    "num_comments": 20,
                },
            ],
            "nbHits": 1000,
            "page": 0,
            "nbPages": 50,
            "hitsPerPage": 100,
        }

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="all",
            mode="search",
            query="CRM",
        )
        page = source.search(task)

        assert len(page.items) == 2
        assert page.items[0].ref_id == "hackernews:12345"
        assert page.items[0].preview == "Ask HN: Best CRM for startups?"
        assert page.exhausted is False
        assert page.next_cursor == "algolia:1"
        assert page.estimated_total == 1000

    def test_pagination_last_page(self, source):
        mock_response = {
            "hits": [{"objectID": "999", "title": "Last item"}],
            "nbHits": 101,
            "page": 1,
            "nbPages": 2,
            "hitsPerPage": 100,
        }

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="all",
            mode="search",
            query="test",
            cursor="algolia:1",
        )
        page = source.search(task)

        assert page.exhausted is True
        assert page.next_cursor is None

    def test_ask_hn_tag_filter(self, source):
        mock_response = {
            "hits": [],
            "nbHits": 0,
            "page": 0,
            "nbPages": 0,
            "hitsPerPage": 100,
        }

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="ask",
            mode="search",
            query="test",
        )
        source.search(task)

        call_args = mock_client.get.call_args
        assert call_args[1]["params"]["tags"] == "ask_hn"


class TestFirebaseListing:
    @pytest.fixture
    def source(self):
        config = HackerNewsConfig(
            rate_limit_per_minute=1000,
            request_delay_seconds=0.0,
        )
        return HackerNewsSource(config)

    def test_listing_pagination(self, source):
        mock_ids = list(range(1, 501))

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_ids
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="ask",
            mode="listing_ask",
            budget=25,
        )
        page = source.search(task)

        assert len(page.items) == 25
        assert page.items[0].ref_id == "hackernews:1"
        assert page.exhausted is False
        assert page.next_cursor == "firebase:25"
        assert page.estimated_total == 500

    def test_listing_continuation(self, source):
        mock_ids = list(range(1, 101))

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_ids
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="top",
            mode="listing_top",
            budget=25,
            cursor="firebase:75",
        )
        page = source.search(task)

        assert len(page.items) == 25
        assert page.items[0].ref_id == "hackernews:76"
        assert page.exhausted is True

    def test_listing_last_batch(self, source):
        mock_ids = list(range(1, 51))

        mock_client = Mock()
        mock_resp = Mock()
        mock_resp.json.return_value = mock_ids
        mock_resp.raise_for_status = Mock()
        mock_client.get.return_value = mock_resp
        source._client = mock_client

        task = SearchTask(
            source="hackernews",
            source_entity="new",
            mode="listing_new",
            budget=100,
        )
        page = source.search(task)

        assert len(page.items) == 50
        assert page.exhausted is True
        assert page.next_cursor is None


class TestFetch:
    @pytest.fixture
    def source(self):
        config = HackerNewsConfig(
            rate_limit_per_minute=1000,
            request_delay_seconds=0.0,
            max_comments_per_story=10,
            comment_depth_limit=2,
        )
        return HackerNewsSource(config)

    def test_fetch_story(self, source):
        mock_item = {
            "id": 12345,
            "type": "story",
            "by": "testuser",
            "time": 1704067200,
            "title": "Ask HN: What tools do you wish existed?",
            "text": "I'm curious what pain points people have.",
            "score": 150,
            "descendants": 89,
            "kids": [],
        }

        with patch.object(source, '_fetch_item') as mock_fetch:
            mock_fetch.return_value = mock_item

            ref = DocumentRef(
                ref_id="hackernews:12345",
                ref_type="story",
                source="hackernews",
                source_entity="ask",
                discovered_from_task_id="test",
            )
            doc = source.fetch(ref, deep_comments="never")

            assert doc.doc_id == "hackernews:12345"
            assert doc.title == "Ask HN: What tools do you wish existed?"
            assert doc.author == "testuser"
            assert doc.score == 150
            assert doc.num_comments == 89
            assert "pain points" in doc.raw_text

    def test_fetch_with_url(self, source):
        mock_item = {
            "id": 12346,
            "type": "story",
            "by": "builder",
            "time": 1704067200,
            "title": "Show HN: My new tool",
            "url": "https://example.com/tool",
            "score": 50,
            "descendants": 20,
        }

        with patch.object(source, '_fetch_item') as mock_fetch:
            mock_fetch.return_value = mock_item

            ref = DocumentRef(
                ref_id="hackernews:12346",
                ref_type="story",
                source="hackernews",
                source_entity="show",
                discovered_from_task_id="test",
            )
            doc = source.fetch(ref, deep_comments="never")

            assert doc.url == "https://example.com/tool"
            assert "https://example.com/tool" in doc.raw_text

    def test_fetch_not_found(self, source):
        with patch.object(source, '_fetch_item') as mock_fetch:
            mock_fetch.return_value = None

            ref = DocumentRef(
                ref_id="hackernews:99999",
                ref_type="story",
                source="hackernews",
                source_entity="all",
                discovered_from_task_id="test",
            )
            
            with pytest.raises(HackerNewsError, match="not found"):
                source.fetch(ref)


class TestCleanHtml:
    @pytest.fixture
    def source(self):
        return HackerNewsSource(HackerNewsConfig())

    def test_clean_paragraph_tags(self, source):
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = source._clean_html(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        assert "<p>" not in result

    def test_clean_links(self, source):
        html = 'Check out <a href="https://example.com">this link</a> for more.'
        result = source._clean_html(html)
        assert "this link (https://example.com)" in result
        assert "<a" not in result

    def test_clean_code_tags(self, source):
        html = "Use <code>pip install</code> to install."
        result = source._clean_html(html)
        assert "`pip install`" in result
        assert "<code>" not in result

    def test_clean_unescape_entities(self, source):
        html = "This &amp; that &lt;test&gt;"
        result = source._clean_html(html)
        assert "This & that <test>" in result


class TestDeepComments:
    @pytest.fixture
    def source(self):
        return HackerNewsSource(HackerNewsConfig())

    def test_should_fetch_always(self, source):
        assert source._should_fetch_comments("always", 0, 0) is True
        assert source._should_fetch_comments("always", 100, 100) is True

    def test_should_fetch_never(self, source):
        assert source._should_fetch_comments("never", 100, 100) is False
        assert source._should_fetch_comments("never", 0, 0) is False

    def test_should_fetch_auto_high_score(self, source):
        assert source._should_fetch_comments("auto", 25, 5) is True
        assert source._should_fetch_comments("auto", 15, 5) is False

    def test_should_fetch_auto_many_comments(self, source):
        assert source._should_fetch_comments("auto", 5, 15) is True
        assert source._should_fetch_comments("auto", 5, 5) is False
