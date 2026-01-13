import pytest
from dataclasses import dataclass
from typing import Callable

from scout.models import (
    SessionState,
    SearchTask,
    DocumentRef,
    Page,
    RawDocument,
    PainSnippet,
    generate_id,
    utc_now,
)
from scout.config import ScoutConfig, FilterConfig, LLMConfig
from scout.filters import ContentFilter
from scout.validation import SnippetValidator, SnippetValidationConfig


@dataclass
class MockSourceConfig:
    name: str = "mock"
    docs_per_search: int = 3
    snippets_per_doc: int = 2


class MockSource:
    def __init__(self, config: MockSourceConfig | None = None):
        self.config = config or MockSourceConfig()
        self.name = self.config.name
        self._doc_counter = 0
        self._search_counter = 0

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        return [
            SearchTask(
                task_id=generate_id(),
                source=self.name,
                source_entity="all",
                mode="search",
                query=q,
            )
            for q in queries
        ]

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        self._search_counter += 1
        refs = [
            DocumentRef(
                ref_id=f"{self.name}:{self._search_counter}:{i}",
                ref_type="post",
                source=self.name,
                source_entity="all",
                discovered_from_task_id=task.task_id,
                rank=i,
            )
            for i in range(self.config.docs_per_search)
        ]
        return Page(items=refs, exhausted=True)

    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        self._doc_counter += 1
        return RawDocument(
            doc_id=ref.ref_id,
            source=self.name,
            source_entity="all",
            url=f"https://example.com/{ref.ref_id}",
            permalink=f"https://example.com/{ref.ref_id}",
            title=f"Test Document {self._doc_counter}",
            raw_text=f"This is test content for document {self._doc_counter}. " * 20,
            author="test_author",
            score=100,
        )


class FailingSource(MockSource):
    def __init__(self, fail_after: int = 0, error_message: str = "Source failed"):
        super().__init__()
        self.name = "failing"
        self.fail_after = fail_after
        self.error_message = error_message
        self._call_count = 0

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        self._call_count += 1
        if self._call_count > self.fail_after:
            raise RuntimeError(self.error_message)
        return super().search(task)


@pytest.fixture
def mock_source() -> MockSource:
    return MockSource()


@pytest.fixture
def failing_source() -> FailingSource:
    return FailingSource()


@pytest.fixture
def test_session() -> SessionState:
    return SessionState(
        session_id="test-session",
        topic="test topic",
        max_iterations=10,
    )


@pytest.fixture
def test_config(tmp_path) -> ScoutConfig:
    return ScoutConfig(
        data_dir=str(tmp_path),
        max_iterations=10,
        max_documents=20,
        parallel_workers=2,
        filter=FilterConfig(min_content_length=50, min_score=0),
        snippet_validation=SnippetValidationConfig(min_confidence=0.3),
        llm=LLMConfig(extraction_prompt_version="v1"),
    )


@pytest.fixture
def content_filter() -> ContentFilter:
    return ContentFilter(FilterConfig(min_content_length=100, min_score=5))


@pytest.fixture
def snippet_validator() -> SnippetValidator:
    return SnippetValidator(
        SnippetValidationConfig(
            min_confidence=0.5,
            min_excerpt_length=10,
            min_pain_statement_length=10,
        )
    )


@pytest.fixture
def sample_document() -> RawDocument:
    return RawDocument(
        doc_id="doc:sample",
        source="test",
        source_entity="all",
        url="https://example.com/sample",
        permalink="https://example.com/sample",
        title="Sample Document",
        raw_text="This is sample content that is long enough to pass the filter. " * 10,
        author="sample_author",
        score=100,
    )


@pytest.fixture
def sample_snippets() -> list[PainSnippet]:
    return [
        PainSnippet(
            doc_id="doc:1",
            excerpt="This tool is really frustrating to use",
            pain_statement="Tool usability issues causing frustration",
            signal_type="complaint",
            intensity=4,
            confidence=0.9,
        ),
        PainSnippet(
            doc_id="doc:1",
            excerpt="I wish there was better documentation",
            pain_statement="Documentation is lacking and hard to follow",
            signal_type="wish",
            intensity=3,
            confidence=0.8,
        ),
        PainSnippet(
            doc_id="doc:2",
            excerpt="We switched to a competitor because of the pricing",
            pain_statement="Pricing drove customer to competitor",
            signal_type="switch",
            intensity=5,
            confidence=0.95,
        ),
    ]
