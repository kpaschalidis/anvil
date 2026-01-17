from __future__ import annotations

import os
from typing import Any


class WebSearchError(RuntimeError):
    pass


def web_search(
    *,
    query: str,
    page: int = 1,
    page_size: int = 5,
    max_results: int | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    days: int | None = None,
    include_raw_content: bool = False,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise WebSearchError("query is required")

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise WebSearchError("TAVILY_API_KEY is not set")

    try:
        from tavily import TavilyClient  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover
        raise WebSearchError(
            "tavily-python is not installed. Install with: `uv sync --extra search`."
        ) from e

    page = max(1, int(page or 1))
    page_size = max(1, min(20, int(page_size or 5)))

    end = page * page_size
    fetch_n = end
    if max_results is not None:
        fetch_n = min(fetch_n, max(1, int(max_results)))

    client = TavilyClient(api_key=api_key)
    payload: dict[str, Any] = {
        "query": query,
        "max_results": fetch_n,
        "include_raw_content": bool(include_raw_content),
    }
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    if days is not None:
        payload["days"] = int(days)

    resp = client.search(**payload)
    results = resp.get("results") if isinstance(resp, dict) else None
    if not isinstance(results, list):
        results = []

    start = (page - 1) * page_size
    sliced = results[start:end]
    has_more = len(results) > end

    return {
        "query": query,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "results": sliced,
    }


WEB_SEARCH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "page": {"type": "integer", "description": "1-based page number", "default": 1},
        "page_size": {
            "type": "integer",
            "description": "Results per page (1-20)",
            "default": 5,
        },
        "max_results": {
            "type": "integer",
            "description": "Hard cap on fetched results (optional)",
        },
        "include_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only include results from these domains",
        },
        "exclude_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exclude results from these domains",
        },
        "days": {
            "type": "integer",
            "description": "Only include results from the last N days (optional)",
        },
        "include_raw_content": {
            "type": "boolean",
            "description": "Ask Tavily to include raw page content when available",
            "default": False,
        },
    },
    "required": ["query"],
}

