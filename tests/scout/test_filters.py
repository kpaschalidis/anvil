import pytest

from scout.filters import ContentFilter, FilterConfig
from scout.models import RawDocument, utc_now


def make_doc(
    *,
    raw_text: str = "x" * 200,
    author: str = "user",
    score: int | None = 100,
) -> RawDocument:
    return RawDocument(
        doc_id="doc:test",
        source="test",
        source_entity="all",
        url="https://example.com/test",
        permalink="https://example.com/test",
        title="Test",
        raw_text=raw_text,
        author=author,
        score=score,
    )


class TestContentFilter:
    def test_passes_valid_document(self):
        filt = ContentFilter(FilterConfig(min_content_length=100, min_score=5))
        doc = make_doc(raw_text="x" * 150, score=10)
        ok, reason = filt.should_extract(doc)
        assert ok is True
        assert reason == "pass"

    def test_rejects_short_content(self):
        filt = ContentFilter(FilterConfig(min_content_length=100, min_score=5))
        doc = make_doc(raw_text="short", score=10)
        ok, reason = filt.should_extract(doc)
        assert ok is False
        assert reason == "too_short"

    def test_rejects_low_score(self):
        filt = ContentFilter(FilterConfig(min_content_length=10, min_score=50))
        doc = make_doc(raw_text="x" * 100, score=5)
        ok, reason = filt.should_extract(doc)
        assert ok is False
        assert reason == "low_score"

    def test_rejects_deleted_author(self):
        filt = ContentFilter(FilterConfig(skip_deleted_authors=True))
        doc = make_doc(author="[deleted]")
        ok, reason = filt.should_extract(doc)
        assert ok is False
        assert reason == "deleted_author"

    def test_allows_deleted_author_when_disabled(self):
        filt = ContentFilter(FilterConfig(skip_deleted_authors=False))
        doc = make_doc(author="[deleted]")
        ok, reason = filt.should_extract(doc)
        assert ok is True

    def test_allows_none_score(self):
        filt = ContentFilter(FilterConfig(min_score=10))
        doc = make_doc(score=None)
        ok, reason = filt.should_extract(doc)
        assert ok is True

    def test_priority_too_short_over_low_score(self):
        filt = ContentFilter(FilterConfig(min_content_length=100, min_score=50))
        doc = make_doc(raw_text="short", score=1)
        ok, reason = filt.should_extract(doc)
        assert ok is False
        assert reason == "too_short"

    def test_zero_min_content_length_passes_all(self):
        filt = ContentFilter(FilterConfig(min_content_length=0, min_score=0))
        doc = make_doc(raw_text="", score=0)
        ok, reason = filt.should_extract(doc)
        assert ok is True


class TestFilterConfig:
    def test_default_values(self):
        cfg = FilterConfig()
        assert cfg.min_content_length == 100
        assert cfg.min_score == 5
        assert cfg.skip_deleted_authors is True

    def test_custom_values(self):
        cfg = FilterConfig(min_content_length=50, min_score=10, skip_deleted_authors=False)
        assert cfg.min_content_length == 50
        assert cfg.min_score == 10
        assert cfg.skip_deleted_authors is False

    def test_frozen(self):
        cfg = FilterConfig()
        with pytest.raises(Exception):
            cfg.min_content_length = 999
