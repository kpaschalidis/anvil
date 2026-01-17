from unittest.mock import Mock

import pytest

from scout.config import GitHubIssuesConfig
from scout.models import SearchTask
from scout.sources.github_issues import GitHubIssuesSource


def _mock_response(*, payload: dict):
    resp = Mock()
    resp.json.return_value = payload
    resp.raise_for_status = Mock()
    return resp


class TestGitHubIssuesSource:
    @pytest.fixture
    def source(self):
        config = GitHubIssuesConfig(token=None, rate_limit_per_minute=1000, request_delay_seconds=0.0, results_per_page=2)
        return GitHubIssuesSource(config)

    def test_search_parses_items_and_paginates(self, source):
        payload = {
            "total_count": 3,
            "incomplete_results": False,
            "items": [
                {
                    "url": "https://api.github.com/repos/acme/repo/issues/1",
                    "html_url": "https://github.com/acme/repo/issues/1",
                    "title": "Bug: crash",
                },
                {
                    "url": "https://api.github.com/repos/acme/repo/issues/2",
                    "html_url": "https://github.com/acme/repo/issues/2",
                    "title": "Feature request",
                },
            ],
        }

        mock_client = Mock()
        mock_client.get.return_value = _mock_response(payload=payload)
        source._client = mock_client

        task = SearchTask(source="github_issues", source_entity="issues", mode="search", query="crm")
        page = source.search(task)

        assert len(page.items) == 2
        assert page.items[0].ref_id.startswith("github_issues:https://api.github.com/repos/acme/repo/issues/1")
        assert page.next_cursor == "page:2"
        assert page.exhausted is False
        assert page.estimated_total == 3

    def test_search_last_page_exhausted(self, source):
        payload = {
            "total_count": 1,
            "items": [
                {
                    "url": "https://api.github.com/repos/acme/repo/issues/1",
                    "html_url": "https://github.com/acme/repo/issues/1",
                    "title": "Bug: crash",
                }
            ],
        }
        mock_client = Mock()
        mock_client.get.return_value = _mock_response(payload=payload)
        source._client = mock_client

        task = SearchTask(
            source="github_issues",
            source_entity="issues",
            mode="search",
            query="crm",
            cursor="page:2",
        )
        page = source.search(task)
        assert page.exhausted is True
        assert page.next_cursor is None

    def test_fetch_builds_raw_document(self, source):
        issue_payload = {
            "title": "Bug: crash",
            "body": "Steps to reproduce...",
            "html_url": "https://github.com/acme/repo/issues/1",
            "created_at": "2024-01-01T00:00:00Z",
            "comments": 5,
            "labels": [{"name": "bug"}, {"name": "high-priority"}],
            "user": {"login": "reporter"},
            "repository_url": "https://api.github.com/repos/acme/repo",
            "url": "https://api.github.com/repos/acme/repo/issues/1",
        }
        source._issue_cache["https://api.github.com/repos/acme/repo/issues/1"] = issue_payload

        ref = Mock(ref_id="github_issues:https://api.github.com/repos/acme/repo/issues/1")
        doc = source.fetch(ref, deep_comments="never")

        assert doc.title == "Bug: crash"
        assert doc.url == "https://github.com/acme/repo/issues/1"
        assert doc.num_comments == 5
        assert doc.author == "reporter"
        assert "Labels:" in doc.raw_text
