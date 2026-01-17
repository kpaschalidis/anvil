import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from scout.config import GitHubIssuesConfig
from scout.models import DocumentRef, Page, RawDocument, SearchTask, SourceEntity
from scout.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class GitHubIssuesError(Exception):
    pass


API_BASE = "https://api.github.com"


def _to_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # GitHub timestamps are ISO8601 with Z suffix
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except Exception:
        return None


class GitHubIssuesSource:
    name = "github_issues"

    def __init__(self, config: GitHubIssuesConfig | None = None):
        self.config = config or GitHubIssuesConfig()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.config.rate_limit_per_minute,
            min_delay=self.config.request_delay_seconds,
        )
        self._client: httpx.Client | None = None
        self._issue_cache: dict[str, dict[str, Any]] = {}

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "scout/0.1",
            }
            if self.config.token:
                headers["Authorization"] = f"Bearer {self.config.token}"
            self._client = httpx.Client(timeout=30.0, headers=headers, follow_redirects=True)
        return self._client

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        return [
            SearchTask(
                source=self.name,
                source_entity="issues",
                mode="search",
                query=q,
            )
            for q in queries
        ]

    def discover(self, topic: str, limit: int = 10) -> list[SourceEntity]:
        return [
            SourceEntity(
                entity_id="github_issues:issues",
                source=self.name,
                name="issues",
                display_name="GitHub Issues (search)",
                description="Search GitHub issues by keyword using the GitHub Search API",
                metadata={"auth": "optional", "env": ["GITHUB_TOKEN", "GH_TOKEN"]},
            )
        ][:limit]

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        if task.mode != "search":
            raise GitHubIssuesError(f"Unknown search mode: {task.mode}")

        query = (task.query or "").strip()
        if not query:
            return Page(items=[], exhausted=True)

        page = 1
        if task.cursor and task.cursor.startswith("page:"):
            try:
                page = max(1, int(task.cursor.split(":", 1)[1]))
            except Exception:
                page = 1

        per_page = max(1, min(100, int(self.config.results_per_page)))

        q = f'{query} in:title,body is:issue'
        params = {"q": q, "per_page": per_page, "page": page}

        self.rate_limiter.wait()
        resp = self.client.get(f"{API_BASE}/search/issues", params=params)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items") or []
        if not isinstance(items, list):
            items = []

        refs: list[DocumentRef] = []
        for rank, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            api_url = it.get("url")
            html_url = it.get("html_url")
            title = it.get("title")
            if not isinstance(api_url, str) or not api_url:
                continue
            self._issue_cache[api_url] = it
            preview = title if isinstance(title, str) and title else html_url or api_url
            refs.append(
                DocumentRef(
                    ref_id=f"github_issues:{api_url}",
                    ref_type="issue",
                    source=self.name,
                    source_entity="issues",
                    discovered_from_task_id=task.task_id,
                    rank=rank,
                    preview=str(preview)[:280],
                )
            )

        total = data.get("total_count")
        try:
            estimated_total = int(total) if total is not None else None
        except Exception:
            estimated_total = None

        # GitHub Search API caps accessible results at 1000.
        reached_api_cap = (page * per_page) >= 1000
        last_page = (len(refs) < per_page) or reached_api_cap
        next_cursor = None if last_page else f"page:{page + 1}"

        return Page(items=refs, next_cursor=next_cursor, exhausted=last_page, estimated_total=estimated_total)

    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        if not ref.ref_id.startswith("github_issues:"):
            raise GitHubIssuesError(f"Invalid ref_id: {ref.ref_id}")
        api_url = ref.ref_id.split(":", 1)[1]
        if not api_url.startswith("http"):
            raise GitHubIssuesError(f"Invalid API URL: {api_url}")

        issue = self._issue_cache.get(api_url)
        if issue is None:
            self.rate_limiter.wait()
            resp = self.client.get(api_url)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403 and "rate limit" in (e.response.text or "").lower():
                    reset = e.response.headers.get("x-ratelimit-reset")
                    remaining = e.response.headers.get("x-ratelimit-remaining")
                    raise GitHubIssuesError(
                        f"GitHub rate limit exceeded (remaining={remaining}, reset={reset}). "
                        "Set GITHUB_TOKEN (or GH_TOKEN) to increase limits."
                    ) from e
                raise
            issue = resp.json()
        if not isinstance(issue, dict):
            raise GitHubIssuesError("Unexpected issue payload")

        title = issue.get("title") or ""
        body = issue.get("body") or ""
        html_url = issue.get("html_url") or api_url

        user = issue.get("user") if isinstance(issue.get("user"), dict) else {}
        author = user.get("login") or user.get("name")

        labels = issue.get("labels")
        label_names: list[str] = []
        if isinstance(labels, list):
            for l in labels:
                if isinstance(l, dict) and isinstance(l.get("name"), str):
                    label_names.append(l["name"])

        repo_url = None
        if isinstance(issue.get("repository_url"), str):
            repo_url = issue["repository_url"]

        created_at = _to_dt(issue.get("created_at"))

        comments = issue.get("comments")
        try:
            num_comments = int(comments) if comments is not None else None
        except Exception:
            num_comments = None

        raw_text_parts: list[str] = []
        if title:
            raw_text_parts.append(str(title))
        if body:
            raw_text_parts.append(str(body))
        if label_names:
            raw_text_parts.append("Labels: " + ", ".join(label_names))
        if repo_url:
            raw_text_parts.append("Repository: " + repo_url)
        raw_text = "\n\n".join([p for p in raw_text_parts if p]).strip()
        if not raw_text:
            raw_text = str(issue)

        return RawDocument(
            doc_id=ref.ref_id,
            source=self.name,
            source_entity="issues",
            url=str(html_url),
            permalink=str(html_url),
            published_at=created_at,
            title=str(title) if title else str(html_url),
            raw_text=raw_text,
            author=str(author) if author else None,
            num_comments=num_comments,
            metadata={"github": {"api_url": api_url, "issue": issue}},
        )
