from scout.sources.base import Source
from scout.sources.reddit import RedditSource
from scout.sources.hackernews import HackerNewsSource
from scout.sources.producthunt import ProductHuntSource
from scout.sources.github_issues import GitHubIssuesSource

__all__ = [
    "Source",
    "RedditSource",
    "HackerNewsSource",
    "ProductHuntSource",
    "GitHubIssuesSource",
]
