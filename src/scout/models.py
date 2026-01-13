import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar
from pydantic import BaseModel, Field


def generate_id() -> str:
    return str(uuid.uuid4())[:8]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RawDocument(BaseModel):
    doc_id: str
    source: str
    source_entity: str
    url: str
    permalink: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    title: str
    raw_text: str
    author: str | None = None
    score: int | None = None
    num_comments: int | None = None
    metadata: dict = Field(default_factory=dict)


class PainSnippet(BaseModel):
    snippet_id: str = Field(default_factory=generate_id)
    doc_id: str
    excerpt: str
    pain_statement: str
    signal_type: str
    intensity: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    extractor_model: str = ""
    extractor_prompt_version: str = ""
    extracted_at: datetime = Field(default_factory=utc_now)
    metadata: dict = Field(default_factory=dict)


class Event(BaseModel):
    event_id: str = Field(default_factory=generate_id)
    session_id: str
    ts: datetime = Field(default_factory=utc_now)
    kind: str
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    decision: str = ""
    metrics: dict = Field(default_factory=dict)


class SearchTask(BaseModel):
    task_id: str = Field(default_factory=generate_id)
    source: str
    source_entity: str
    mode: str
    query: str | None = None
    sort: str | None = None
    time_filter: str | None = None
    cursor: str | None = None
    budget: int = 25
    created_at: datetime = Field(default_factory=utc_now)


class DocumentRef(BaseModel):
    ref_id: str
    ref_type: str
    source: str
    source_entity: str
    discovered_from_task_id: str
    rank: int = 0
    preview: str | None = None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None
    exhausted: bool = False
    estimated_total: int | None = None


class SourceEntity(BaseModel):
    entity_id: str
    source: str
    name: str
    display_name: str
    description: str | None = None
    subscriber_count: int | None = None
    metadata: dict = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    snippets: list[PainSnippet] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)
    novelty: float = Field(default=0.5, ge=0.0, le=1.0)


class SessionStats(BaseModel):
    docs_collected: int = 0
    snippets_extracted: int = 0
    tasks_completed: int = 0
    tasks_remaining: int = 0
    iterations: int = 0
    avg_novelty: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    llm_calls: int = 0
    extraction_calls: int = 0
    complexity_calls: int = 0


class SessionState(BaseModel):
    session_id: str
    topic: str
    status: str = "running"
    extraction_prompt_version: str = "v1"
    task_queue: list[SearchTask] = Field(default_factory=list)
    visited_tasks: list[str] = Field(default_factory=list)
    visited_docs: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    novelty_history: list[float] = Field(default_factory=list)
    cursors: dict[str, str] = Field(default_factory=dict)
    stats: SessionStats = Field(default_factory=SessionStats)
    complexity: str | None = None
    max_iterations: int = 60
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
