from __future__ import annotations

import time
from dataclasses import dataclass

from common.events import DocumentEvent, ErrorEvent, EventCallback, EventEmitter, ProgressEvent
from scout.config import ScoutConfig
from scout.models import RawDocument, SearchTask, generate_id
from scout.sources.registry import load_source_classes
from scout.storage import Storage


@dataclass(frozen=True, slots=True)
class FetchConfig:
    topic: str
    sources: list[str]
    data_dir: str = "data/sessions"
    max_documents: int = 100
    deep_comments: str = "auto"
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    session_id: str
    documents_fetched: int
    duration_seconds: float
    errors: list[str]


def _default_queries(topic: str) -> list[str]:
    topic = (topic or "").strip()
    if not topic:
        return []
    return [
        topic,
        f"{topic} pain points",
        f"{topic} problems",
        f"{topic} alternatives",
    ]


def _build_sources(config: ScoutConfig, names: list[str]):
    classes = load_source_classes()
    sources = []
    for name in names:
        cls = classes.get(name)
        if not cls:
            continue
        if name == "hackernews":
            sources.append(cls(config.hackernews))
        elif name == "reddit":
            if config.reddit is None:
                continue
            sources.append(cls(config.reddit))
        elif name == "producthunt":
            sources.append(cls(config.producthunt))
        elif name == "github_issues":
            sources.append(cls(config.github_issues))
        else:
            try:
                sources.append(cls())
            except Exception:
                continue
    return sources


class FetchService:
    def __init__(self, config: FetchConfig, *, on_event: EventCallback = None):
        self.config = config
        self.emitter = EventEmitter(on_event)

    def run(
        self,
        *,
        scout_config: ScoutConfig | None = None,
        sources: list | None = None,
    ) -> FetchResult:
        started = time.time()
        errors: list[str] = []

        topic = (self.config.topic or "").strip()
        if not topic:
            raise ValueError("topic is required")

        source_names = [s.strip() for s in (self.config.sources or []) if s.strip()]
        if not source_names:
            raise ValueError("at least one source is required")

        session_id = self.config.session_id or generate_id()

        if sources is None:
            if scout_config is None:
                scout_config = ScoutConfig.from_profile("quick", sources=source_names)
            scout_config.data_dir = self.config.data_dir
            scout_config.max_documents = self.config.max_documents
            scout_config.deep_comments = self.config.deep_comments

            sources = _build_sources(scout_config, source_names)
            if not sources:
                raise ValueError("no sources configured")

        storage = Storage(session_id, self.config.data_dir)
        try:
            seen_doc_ids: set[str] = set()
            docs_fetched_ref: list[int] = [0]

            self.emitter.emit(
                ProgressEvent(stage="start", current=0, total=None, message="Starting fetch")
            )

            queries = _default_queries(topic)

            for source in sources:
                if docs_fetched_ref[0] >= self.config.max_documents:
                    break

                try:
                    tasks = source.adapt_queries(queries, topic)
                except Exception as e:
                    msg = f"{source.name}: failed to adapt queries: {e}"
                    errors.append(msg)
                    self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                    continue

                for task in tasks:
                    if docs_fetched_ref[0] >= self.config.max_documents:
                        break
                    self._run_task(
                        source=source,
                        task=task,
                        storage=storage,
                        seen_doc_ids=seen_doc_ids,
                        docs_fetched_ref=docs_fetched_ref,
                        errors=errors,
                    )

            duration = time.time() - started
            self.emitter.emit(
                ProgressEvent(
                    stage="done",
                    current=docs_fetched_ref[0],
                    total=self.config.max_documents,
                    message=f"Fetched {docs_fetched_ref[0]} documents",
                )
            )

            return FetchResult(
                session_id=session_id,
                documents_fetched=docs_fetched_ref[0],
                duration_seconds=duration,
                errors=errors,
            )
        finally:
            storage.close()

    def _run_task(
        self,
        *,
        source,
        task: SearchTask,
        storage: Storage,
        seen_doc_ids: set[str],
        docs_fetched_ref: list[int],
        errors: list[str],
    ) -> None:
        cursor_task = task
        while docs_fetched_ref[0] < self.config.max_documents:
            try:
                page = source.search(cursor_task)
            except Exception as e:
                msg = f"{source.name}: search failed: {e}"
                errors.append(msg)
                self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                return

            for ref in page.items:
                if docs_fetched_ref[0] >= self.config.max_documents:
                    return
                if ref.ref_id in seen_doc_ids:
                    continue

                try:
                    doc: RawDocument = source.fetch(ref, deep_comments=self.config.deep_comments)
                except Exception as e:
                    msg = f"{source.name}: fetch failed for {ref.ref_id}: {e}"
                    errors.append(msg)
                    self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                    seen_doc_ids.add(ref.ref_id)
                    continue

                try:
                    storage.save_document(doc)
                except Exception as e:
                    msg = f"{source.name}: storage failed for {ref.ref_id}: {e}"
                    errors.append(msg)
                    self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                    seen_doc_ids.add(ref.ref_id)
                    continue

                seen_doc_ids.add(ref.ref_id)
                docs_fetched_ref[0] += 1
                self.emitter.emit(DocumentEvent(doc_id=doc.doc_id, title=doc.title, source=source.name))
                self.emitter.emit(
                    ProgressEvent(
                        stage="fetch",
                        current=docs_fetched_ref[0],
                        total=self.config.max_documents,
                        message=f"{source.name}: {doc.title}",
                    )
                )

            if page.exhausted or not page.next_cursor:
                return

            cursor_task = SearchTask(**{**task.model_dump(), "cursor": page.next_cursor})
