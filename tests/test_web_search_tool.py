import os
import sys
import types

import pytest

from anvil.tools.search import WebSearchError, web_search


def test_web_search_requires_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(WebSearchError):
        web_search(query="test")


def test_web_search_missing_dependency(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    # Simulate missing dependency by providing a module without TavilyClient.
    monkeypatch.setitem(sys.modules, "tavily", types.SimpleNamespace())
    with pytest.raises(WebSearchError):
        web_search(query="test")


def test_web_search_pagination_slices_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "x")

    class FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def search(self, **kwargs):
            n = kwargs.get("max_results", 0)
            return {"results": [{"url": f"https://e/{i}", "title": str(i)} for i in range(n)]}

    fake_mod = types.SimpleNamespace(TavilyClient=FakeClient)
    monkeypatch.setitem(sys.modules, "tavily", fake_mod)

    out = web_search(query="q", page=2, page_size=3)
    assert out["page"] == 2
    assert out["page_size"] == 3
    assert [r["url"] for r in out["results"]] == ["https://e/3", "https://e/4", "https://e/5"]
