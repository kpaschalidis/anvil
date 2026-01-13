import functools
import html
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar, Callable, ParamSpec

import httpx

from scout.config import HackerNewsConfig
from scout.rate_limiter import RateLimiter
from scout.models import (
    SearchTask,
    Page,
    DocumentRef,
    RawDocument,
    SourceEntity,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

FIREBASE_BASE_URL = "https://hacker-news.firebaseio.com/v0"
ALGOLIA_BASE_URL = "https://hn.algolia.com/api/v1"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HackerNewsError(Exception):
    pass


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: float = 0.1


def with_retry(func: Callable[P, T]) -> Callable[P, T]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        config = RetryConfig()
        last_exception: Exception | None = None

        for attempt in range(config.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except httpx.HTTPStatusError as e:
                last_exception = e
                status = e.response.status_code
                if status not in RETRYABLE_STATUS_CODES:
                    raise

                if attempt == config.max_retries:
                    raise

                delay = min(
                    config.base_delay * (config.exponential_base**attempt),
                    config.max_delay,
                )
                delay += random.uniform(0, config.jitter * delay)

                logger.warning(
                    f"Retry {attempt + 1}/{config.max_retries} after {delay:.1f}s: {e}"
                )
                time.sleep(delay)

            except httpx.RequestError as e:
                last_exception = e
                if attempt == config.max_retries:
                    raise

                delay = min(
                    config.base_delay * (config.exponential_base**attempt),
                    config.max_delay,
                )
                delay += random.uniform(0, config.jitter * delay)

                logger.warning(
                    f"Retry {attempt + 1}/{config.max_retries} after {delay:.1f}s: {e}"
                )
                time.sleep(delay)

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")

    return wrapper


class HackerNewsSource:
    name = "hackernews"

    LISTING_ENDPOINTS = {
        "ask": "askstories",
        "show": "showstories",
        "top": "topstories",
        "new": "newstories",
        "best": "beststories",
        "job": "jobstories",
    }

    def __init__(self, config: HackerNewsConfig | None = None):
        self.config = config or HackerNewsConfig()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.config.rate_limit_per_minute,
            min_delay=self.config.request_delay_seconds,
        )
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        tasks: list[SearchTask] = []

        for query in queries:
            tasks.append(
                SearchTask(
                    source="hackernews",
                    source_entity="all",
                    mode="search",
                    query=query,
                )
            )
            tasks.append(
                SearchTask(
                    source="hackernews",
                    source_entity="ask",
                    mode="search",
                    query=query,
                )
            )

        return tasks

    def discover(self, topic: str, limit: int = 10) -> list[SourceEntity]:
        entities = [
            SourceEntity(
                entity_id="hackernews:ask",
                source="hackernews",
                name="ask",
                display_name="Ask HN",
                description="Questions and discussions from the HN community",
            ),
            SourceEntity(
                entity_id="hackernews:show",
                source="hackernews",
                name="show",
                display_name="Show HN",
                description="Projects and products shared by the HN community",
            ),
            SourceEntity(
                entity_id="hackernews:top",
                source="hackernews",
                name="top",
                display_name="Top Stories",
                description="Current top stories on Hacker News",
            ),
            SourceEntity(
                entity_id="hackernews:best",
                source="hackernews",
                name="best",
                display_name="Best Stories",
                description="Highest scoring stories on Hacker News",
            ),
            SourceEntity(
                entity_id="hackernews:new",
                source="hackernews",
                name="new",
                display_name="New Stories",
                description="Most recent stories on Hacker News",
            ),
        ]
        return entities[:limit]

    @with_retry
    def search(self, task: SearchTask) -> Page[DocumentRef]:
        if task.mode == "search":
            return self._search_algolia(task)
        elif task.mode.startswith("listing_"):
            return self._search_listing(task)
        else:
            raise HackerNewsError(f"Unknown search mode: {task.mode}")

    def _search_algolia(self, task: SearchTask) -> Page[DocumentRef]:
        self.rate_limiter.wait()

        page_num = 0
        if task.cursor and task.cursor.startswith("algolia:"):
            page_num = int(task.cursor.split(":")[1])

        params = {
            "query": task.query or "",
            "page": page_num,
            "hitsPerPage": self.config.hits_per_page,
        }

        if task.source_entity == "ask":
            params["tags"] = "ask_hn"
        elif task.source_entity == "show":
            params["tags"] = "show_hn"
        elif task.source_entity != "all":
            params["tags"] = "story"

        url = f"{ALGOLIA_BASE_URL}/search"
        response = self.client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        refs: list[DocumentRef] = []
        for rank, hit in enumerate(data.get("hits", [])):
            object_id = hit.get("objectID")
            if not object_id:
                continue

            refs.append(
                DocumentRef(
                    ref_id=f"hackernews:{object_id}",
                    ref_type="story",
                    source="hackernews",
                    source_entity=task.source_entity,
                    discovered_from_task_id=task.task_id,
                    rank=rank + (page_num * self.config.hits_per_page),
                    preview=hit.get("title", "")[:200],
                )
            )

        nb_pages = data.get("nbPages", 1)
        nb_hits = data.get("nbHits", 0)

        next_cursor = None
        exhausted = True
        if page_num + 1 < nb_pages:
            next_cursor = f"algolia:{page_num + 1}"
            exhausted = False

        logger.info(
            f"Algolia search '{task.query}' page {page_num}: "
            f"{len(refs)} hits, exhausted={exhausted}, total={nb_hits}"
        )

        return Page(
            items=refs,
            next_cursor=next_cursor,
            exhausted=exhausted,
            estimated_total=nb_hits,
        )

    def _search_listing(self, task: SearchTask) -> Page[DocumentRef]:
        self.rate_limiter.wait()

        listing_type = task.mode.replace("listing_", "")
        endpoint = self.LISTING_ENDPOINTS.get(listing_type)
        if not endpoint:
            raise HackerNewsError(f"Unknown listing type: {listing_type}")

        start_idx = 0
        if task.cursor and task.cursor.startswith("firebase:"):
            start_idx = int(task.cursor.split(":")[1])

        url = f"{FIREBASE_BASE_URL}/{endpoint}.json"
        response = self.client.get(url)
        response.raise_for_status()
        all_ids: list[int] = response.json() or []

        batch_ids = all_ids[start_idx : start_idx + task.budget]

        refs: list[DocumentRef] = []
        for rank, item_id in enumerate(batch_ids):
            refs.append(
                DocumentRef(
                    ref_id=f"hackernews:{item_id}",
                    ref_type="story",
                    source="hackernews",
                    source_entity=task.source_entity,
                    discovered_from_task_id=task.task_id,
                    rank=start_idx + rank,
                    preview=None,
                )
            )

        next_cursor = None
        exhausted = True
        if start_idx + task.budget < len(all_ids):
            next_cursor = f"firebase:{start_idx + task.budget}"
            exhausted = False

        logger.info(
            f"Listing {listing_type} from {start_idx}: "
            f"{len(refs)} items, exhausted={exhausted}, total={len(all_ids)}"
        )

        return Page(
            items=refs,
            next_cursor=next_cursor,
            exhausted=exhausted,
            estimated_total=len(all_ids),
        )

    @with_retry
    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        item_id = ref.ref_id.replace("hackernews:", "")
        item = self._fetch_item(int(item_id))

        if not item:
            raise HackerNewsError(f"Item {item_id} not found")

        title = item.get("title", "")
        text = self._clean_html(item.get("text", ""))
        url = item.get("url", "")
        author = item.get("by", "[deleted]")
        score = item.get("score", 0)
        num_comments = item.get("descendants", 0)
        created_at = item.get("time", 0)

        comment_text = ""
        if deep_comments != "never":
            should_fetch = self._should_fetch_comments(
                deep_comments, score, num_comments
            )
            if should_fetch:
                comment_text = self._fetch_comments(item)

        raw_text = f"{title}\n\n"
        if text:
            raw_text += f"{text}\n\n"
        if url:
            raw_text += f"Link: {url}\n\n"
        if comment_text:
            raw_text += f"--- COMMENTS ---\n{comment_text}"

        published_at = datetime.fromtimestamp(created_at, tz=timezone.utc)
        permalink = f"https://news.ycombinator.com/item?id={item_id}"

        doc = RawDocument(
            doc_id=f"hackernews:{item_id}",
            source="hackernews",
            source_entity=ref.source_entity,
            url=url or permalink,
            permalink=permalink,
            published_at=published_at,
            title=title,
            raw_text=raw_text,
            author=author,
            score=score,
            num_comments=num_comments,
            metadata={
                "item_type": item.get("type", "story"),
                "has_url": bool(url),
                "comments_fetched": bool(comment_text),
            },
        )

        logger.debug(f"Fetched {doc.doc_id}: {len(raw_text)} chars")
        return doc

    def _fetch_item(self, item_id: int) -> dict | None:
        self.rate_limiter.wait()
        url = f"{FIREBASE_BASE_URL}/item/{item_id}.json"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def _should_fetch_comments(
        self, deep_comments: str, score: int, num_comments: int
    ) -> bool:
        if deep_comments == "always":
            return True
        if deep_comments == "auto":
            return score > 20 or num_comments > 10
        return False

    def _fetch_comments(self, item: dict) -> str:
        kids = item.get("kids", [])
        if not kids:
            return ""

        comments_parts: list[str] = []
        comment_count = 0

        def fetch_recursive(item_ids: list[int], depth: int = 0) -> None:
            nonlocal comment_count
            if depth > self.config.comment_depth_limit:
                return
            if comment_count >= self.config.max_comments_per_story:
                return

            for cid in item_ids:
                if comment_count >= self.config.max_comments_per_story:
                    break

                comment = self._fetch_item(cid)
                if not comment:
                    continue

                if comment.get("deleted") or comment.get("dead"):
                    continue

                text = self._clean_html(comment.get("text", ""))
                if not text:
                    continue

                author = comment.get("by", "[deleted]")
                indent = "  " * depth
                comments_parts.append(f"{indent}[{author}]\n{indent}{text}\n")
                comment_count += 1

                child_ids = comment.get("kids", [])
                if child_ids and depth < self.config.comment_depth_limit:
                    fetch_recursive(child_ids, depth + 1)

        fetch_recursive(kids)
        logger.debug(f"Fetched {comment_count} comments")
        return "\n---\n".join(comments_parts)

    def _clean_html(self, text: str) -> str:
        if not text:
            return ""
        text = text.replace("<p>", "\n\n")
        text = text.replace("</p>", "")
        text = text.replace("<br>", "\n")
        text = text.replace("<br/>", "\n")
        text = text.replace("<i>", "")
        text = text.replace("</i>", "")
        text = text.replace("<b>", "")
        text = text.replace("</b>", "")
        text = text.replace("<code>", "`")
        text = text.replace("</code>", "`")
        text = text.replace("<pre>", "\n```\n")
        text = text.replace("</pre>", "\n```\n")
        text = re.sub(r'<a\s+href="([^"]*)"[^>]*>([^<]*)</a>', r"\2 (\1)", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        return text.strip()

    def __del__(self):
        if self._client:
            self._client.close()
