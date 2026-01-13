import functools
import random
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, TypeVar, Callable, ParamSpec

import praw
from praw.models import Submission, Subreddit
from prawcore.exceptions import ResponseException, RequestException

from scout.config import RedditConfig
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

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RedditError(Exception):
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
            except (ResponseException, RequestException) as e:
                last_exception = e

                is_retryable = True
                if hasattr(e, "response") and e.response is not None:
                    status = getattr(e.response, "status_code", None)
                    if status is not None and status not in RETRYABLE_STATUS_CODES:
                        is_retryable = False

                if not is_retryable:
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

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")

    return wrapper


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60, min_delay: float = 1.0):
        self.requests_per_minute = requests_per_minute
        self.min_delay = min_delay
        self.last_request_time: float = 0.0
        self.request_count: int = 0
        self.window_start: float = time.time()

    def wait(self) -> None:
        now = time.time()

        if now - self.window_start >= 60:
            self.window_start = now
            self.request_count = 0

        if self.request_count >= self.requests_per_minute:
            sleep_time = 60 - (now - self.window_start)
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self.window_start = time.time()
            self.request_count = 0

        elapsed = now - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

        self.last_request_time = time.time()
        self.request_count += 1


class RedditSource:
    name = "reddit"

    def __init__(self, config: RedditConfig | None = None):
        self.config = config or RedditConfig()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.config.rate_limit_per_minute,
            min_delay=self.config.request_delay_seconds,
        )
        self._reddit: praw.Reddit | None = None

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        tasks: list[SearchTask] = []
        for query in queries:
            tasks.append(
                SearchTask(
                    source="reddit",
                    source_entity="all",
                    mode="search",
                    query=query,
                )
            )
            tasks.append(
                SearchTask(
                    source="reddit",
                    source_entity="all",
                    mode="search",
                    query=f"{query} problems",
                )
            )
        tasks.append(
            SearchTask(
                source="reddit",
                source_entity="all",
                mode="search",
                query=f"{topic} frustrating",
            )
        )
        return tasks

    @property
    def reddit(self) -> praw.Reddit:
        if self._reddit is None:
            self._reddit = praw.Reddit(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                user_agent=self.config.user_agent,
            )
            logger.info(
                f"Reddit client initialized with user agent: {self.config.user_agent}"
            )
        return self._reddit

    @with_retry
    def discover(self, topic: str, limit: int = 10) -> list[SourceEntity]:
        self.rate_limiter.wait()
        entities: list[SourceEntity] = []

        try:
            for subreddit in self.reddit.subreddits.search(topic, limit=limit):
                entities.append(
                    SourceEntity(
                        entity_id=f"reddit:r/{subreddit.display_name}",
                        source="reddit",
                        name=subreddit.display_name,
                        display_name=f"r/{subreddit.display_name}",
                        description=(
                            subreddit.public_description[:500]
                            if subreddit.public_description
                            else None
                        ),
                        subscriber_count=subreddit.subscribers,
                        metadata={
                            "subreddit_type": subreddit.subreddit_type,
                            "over18": subreddit.over18,
                            "created_utc": subreddit.created_utc,
                        },
                    )
                )
            logger.info(f"Discovered {len(entities)} subreddits for topic '{topic}'")
        except (ResponseException, RequestException) as e:
            logger.error(f"Failed to discover subreddits for '{topic}': {e}")
            raise RedditError(f"Subreddit discovery failed: {e}") from e

        return entities

    @with_retry
    def search(self, task: SearchTask) -> Page[DocumentRef]:
        self.rate_limiter.wait()
        refs: list[DocumentRef] = []
        next_cursor: str | None = None
        exhausted = False

        try:
            if task.source_entity == "all":
                subreddit = self.reddit.subreddit("all")
            else:
                subreddit_name = task.source_entity.lstrip("r/")
                subreddit = self.reddit.subreddit(subreddit_name)

            submissions: Iterator[Submission]

            if task.mode == "search":
                submissions = self._search_subreddit(
                    subreddit,
                    task.query or "",
                    task.sort or "relevance",
                    task.time_filter or "all",
                    task.budget,
                    task.cursor,
                )
            elif task.mode.startswith("listing_"):
                listing_type = task.mode.replace("listing_", "")
                submissions = self._get_listing(
                    subreddit,
                    listing_type,
                    task.time_filter,
                    task.budget,
                    task.cursor,
                )
            else:
                raise RedditError(f"Unknown search mode: {task.mode}")

            for rank, submission in enumerate(submissions):
                refs.append(
                    DocumentRef(
                        ref_id=f"reddit:{submission.fullname}",
                        ref_type="submission",
                        source="reddit",
                        source_entity=task.source_entity,
                        discovered_from_task_id=task.task_id,
                        rank=rank,
                        preview=submission.title[:200] if submission.title else None,
                    )
                )
                next_cursor = submission.fullname

            if len(refs) < task.budget:
                exhausted = True

            logger.info(
                f"Search task {task.task_id}: found {len(refs)} refs, "
                f"exhausted={exhausted}, cursor={next_cursor}"
            )

        except (ResponseException, RequestException) as e:
            logger.error(f"Search failed for task {task.task_id}: {e}")
            raise RedditError(f"Search failed: {e}") from e

        return Page(
            items=refs,
            next_cursor=next_cursor,
            exhausted=exhausted,
            estimated_total=None,
        )

    def _search_subreddit(
        self,
        subreddit: Subreddit,
        query: str,
        sort: str,
        time_filter: str,
        limit: int,
        after: str | None,
    ) -> Iterator[Submission]:
        params = {"after": after} if after else {}
        return subreddit.search(
            query,
            sort=sort,
            time_filter=time_filter,
            limit=limit,
            params=params,
        )

    def _get_listing(
        self,
        subreddit: Subreddit,
        listing_type: str,
        time_filter: str | None,
        limit: int,
        after: str | None,
    ) -> Iterator[Submission]:
        params = {"after": after} if after else {}

        if listing_type == "new":
            return subreddit.new(limit=limit, params=params)
        elif listing_type == "hot":
            return subreddit.hot(limit=limit, params=params)
        elif listing_type == "rising":
            return subreddit.rising(limit=limit, params=params)
        elif listing_type == "top":
            return subreddit.top(
                time_filter=time_filter or "all", limit=limit, params=params
            )
        elif listing_type == "controversial":
            return subreddit.controversial(
                time_filter=time_filter or "all", limit=limit, params=params
            )
        else:
            raise RedditError(f"Unknown listing type: {listing_type}")

    @with_retry
    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        self.rate_limiter.wait()

        submission_id = ref.ref_id.replace("reddit:", "").replace("t3_", "")

        try:
            submission = self.reddit.submission(id=submission_id)

            submission._fetch()

            comment_text = self._fetch_comments(submission, deep_comments)

            raw_text = f"{submission.title}\n\n"
            if submission.selftext:
                raw_text += f"{submission.selftext}\n\n"
            if comment_text:
                raw_text += f"--- COMMENTS ---\n{comment_text}"

            published_at = datetime.fromtimestamp(
                submission.created_utc, tz=timezone.utc
            )

            doc = RawDocument(
                doc_id=f"reddit:{submission.fullname}",
                source="reddit",
                source_entity=f"r/{submission.subreddit.display_name}",
                url=f"https://reddit.com{submission.permalink}",
                permalink=submission.permalink,
                published_at=published_at,
                title=submission.title,
                raw_text=raw_text,
                author=str(submission.author) if submission.author else "[deleted]",
                score=submission.score,
                num_comments=submission.num_comments,
                metadata={
                    "subreddit": submission.subreddit.display_name,
                    "upvote_ratio": submission.upvote_ratio,
                    "is_self": submission.is_self,
                    "link_flair_text": submission.link_flair_text,
                    "over_18": submission.over_18,
                    "spoiler": submission.spoiler,
                    "stickied": submission.stickied,
                    "locked": submission.locked,
                    "distinguished": submission.distinguished,
                    "comments_fetched": len(comment_text) > 0,
                },
            )

            logger.debug(f"Fetched document {doc.doc_id}: {len(raw_text)} chars")
            return doc

        except (ResponseException, RequestException) as e:
            logger.error(f"Failed to fetch {ref.ref_id}: {e}")
            raise RedditError(f"Fetch failed for {ref.ref_id}: {e}") from e

    def _fetch_comments(self, submission: Submission, deep_comments: str) -> str:
        if deep_comments == "never":
            return ""

        should_deep_fetch = False
        if deep_comments == "always":
            should_deep_fetch = True
        elif deep_comments == "auto":
            should_deep_fetch = (
                submission.score > 50
                or submission.num_comments > 20
                or submission.upvote_ratio > 0.9
            )

        self.rate_limiter.wait()

        if should_deep_fetch:
            submission.comments.replace_more(limit=None)
        else:
            submission.comments.replace_more(limit=0)

        comments_text_parts: list[str] = []
        comment_count = 0
        max_comments = 50 if should_deep_fetch else 20

        for comment in submission.comments.list()[:max_comments]:
            if (
                hasattr(comment, "body")
                and comment.body
                and comment.body != "[deleted]"
            ):
                author = str(comment.author) if comment.author else "[deleted]"
                score = getattr(comment, "score", 0)
                comments_text_parts.append(
                    f"[{author}] (score: {score})\n{comment.body}\n"
                )
                comment_count += 1

        logger.debug(f"Fetched {comment_count} comments (deep={should_deep_fetch})")
        return "\n---\n".join(comments_text_parts)
