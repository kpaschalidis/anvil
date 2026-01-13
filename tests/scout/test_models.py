import pytest
from datetime import datetime

from scout.models import (
    RawDocument,
    PainSnippet,
    Event,
    SearchTask,
    DocumentRef,
    Page,
    SourceEntity,
    ExtractionResult,
    SessionState,
    SessionStats,
    generate_id,
    utc_now,
)


class TestModels:
    def test_generate_id(self):
        id1 = generate_id()
        id2 = generate_id()
        assert len(id1) == 8
        assert id1 != id2

    def test_utc_now(self):
        now = utc_now()
        assert isinstance(now, datetime)

    def test_raw_document(self):
        doc = RawDocument(
            doc_id="test:123",
            source="reddit",
            source_entity="r/test",
            url="https://reddit.com/r/test/123",
            permalink="/r/test/comments/123",
            title="Test Post",
            raw_text="This is test content",
        )
        assert doc.doc_id == "test:123"
        assert doc.source == "reddit"
        assert doc.retrieved_at is not None

    def test_pain_snippet(self):
        snippet = PainSnippet(
            doc_id="test:123",
            excerpt="I hate this product",
            pain_statement="Product is frustrating",
            signal_type="complaint",
            intensity=4,
            confidence=0.9,
            entities=["ProductX"],
            extractor_model="gpt-4o",
            extractor_prompt_version="v1",
        )
        assert snippet.snippet_id
        assert snippet.intensity == 4
        assert snippet.confidence == 0.9

    def test_pain_snippet_validation(self):
        with pytest.raises(ValueError):
            PainSnippet(
                doc_id="test:123",
                excerpt="test",
                pain_statement="test",
                signal_type="complaint",
                intensity=10,
                confidence=0.5,
            )

        with pytest.raises(ValueError):
            PainSnippet(
                doc_id="test:123",
                excerpt="test",
                pain_statement="test",
                signal_type="complaint",
                intensity=3,
                confidence=1.5,
            )

    def test_search_task(self):
        task = SearchTask(
            source="reddit",
            source_entity="r/test",
            mode="search",
            query="test problems",
        )
        assert task.task_id
        assert task.budget == 25
        assert task.cursor is None

    def test_document_ref(self):
        ref = DocumentRef(
            ref_id="reddit:t3_abc",
            ref_type="submission",
            source="reddit",
            source_entity="r/test",
            discovered_from_task_id="task123",
            rank=0,
            preview="Test title",
        )
        assert ref.ref_id == "reddit:t3_abc"

    def test_page(self):
        refs = [
            DocumentRef(
                ref_id=f"ref_{i}",
                ref_type="submission",
                source="reddit",
                source_entity="r/test",
                discovered_from_task_id="task1",
            )
            for i in range(5)
        ]
        page: Page[DocumentRef] = Page(
            items=refs,
            next_cursor="cursor123",
            exhausted=False,
        )
        assert len(page.items) == 5
        assert page.next_cursor == "cursor123"

    def test_extraction_result(self):
        result = ExtractionResult(
            snippets=[],
            entities=["ProductA", "ProductB"],
            follow_up_queries=["query 1"],
            novelty=0.8,
        )
        assert result.novelty == 0.8
        assert len(result.entities) == 2

    def test_session_state(self):
        session = SessionState(
            session_id="abc123",
            topic="test topic",
        )
        assert session.status == "running"
        assert session.max_iterations == 60
        assert len(session.task_queue) == 0

    def test_session_stats(self):
        stats = SessionStats(
            docs_collected=10,
            snippets_extracted=25,
        )
        assert stats.docs_collected == 10
        assert stats.avg_novelty == 0.0
