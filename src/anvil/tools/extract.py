from __future__ import annotations

import hashlib
import os
from typing import Any


class WebExtractError(RuntimeError):
    pass


def web_extract(
    *,
    url: str,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise WebExtractError("url is required")

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise WebExtractError("TAVILY_API_KEY is not set")

    try:
        from tavily import TavilyClient  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover
        raise WebExtractError(
            "tavily-python is not installed. Install with: `uv sync --extra search`."
        ) from e

    max_chars = max(1, int(max_chars or 20_000))

    client = TavilyClient(api_key=api_key)
    resp = client.extract(urls=[url])
    results = resp.get("results") if isinstance(resp, dict) else None
    if not isinstance(results, list) or not results:
        return {
            "url": url,
            "title": "",
            "raw_content": "",
            "raw_len": 0,
            "truncated": False,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }

    first = results[0] if isinstance(results[0], dict) else {}
    raw = first.get("raw_content") or ""
    if not isinstance(raw, str):
        raw = ""
    title = first.get("title") or ""
    if not isinstance(title, str):
        title = ""

    raw_len = len(raw)
    truncated = raw_len > max_chars
    if truncated:
        raw = raw[:max_chars]

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "url": url,
        "title": title.strip(),
        "raw_content": raw,
        "raw_len": raw_len,
        "truncated": truncated,
        "sha256": digest,
    }


WEB_EXTRACT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "URL to extract content from"},
        "max_chars": {
            "type": "integer",
            "description": "Max characters to return (truncates raw_content)",
            "default": 20000,
        },
    },
    "required": ["url"],
}

