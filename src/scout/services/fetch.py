from __future__ import annotations

import time
from dataclasses import dataclass

from common.events import DocumentEvent, ErrorEvent, EventCallback, EventEmitter, ProgressEvent
from scout.config import ScoutConfig
from scout.models import RawDocument, SearchTask, SessionState, generate_id, utc_now
from scout.session import SessionManager, SessionError
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
    resume: bool = False
    max_task_pages: int = 25
    write_meta: bool = False


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
        if not topic and not self.config.resume:
            raise ValueError("topic is required (or pass resume=True)")

        source_names = [s.strip() for s in (self.config.sources or []) if s.strip()]
        if not source_names:
            raise ValueError("at least one source is required")

        session = self._load_or_create_session(topic=topic)
        session_id = session.session_id
        if not topic:
            topic = session.topic

        if self.config.write_meta:
            self._write_meta(
                session_id=session_id,
                topic=topic,
                status="running",
                config={
                    "sources": source_names,
                    "max_documents": int(self.config.max_documents),
                    "max_task_pages": int(self.config.max_task_pages),
                    "deep_comments": self.config.deep_comments,
                    "resume": bool(self.config.resume),
                },
            )

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
        succeeded = False
        try:
            seen_doc_ids: set[str] = set(session.visited_docs)
            docs_fetched_ref: list[int] = [int(session.stats.docs_collected or 0)]

            self.emitter.emit(
                ProgressEvent(stage="start", current=0, total=None, message="Starting fetch")
            )

            if not session.task_queue:
                queries = _default_queries(topic)
                for source in sources:
                    try:
                        tasks = source.adapt_queries(queries, topic)
                        for t in tasks:
                            t.budget = max(1, min(int(t.budget), int(self.config.max_task_pages)))
                        session.task_queue.extend(tasks)
                    except Exception as e:
                        msg = f"{source.name}: failed to adapt queries: {e}"
                        errors.append(msg)
                        self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                session.stats.tasks_remaining = len(session.task_queue)
                self._save_session(session)

            sources_by_name = {s.name: s for s in sources}
            while session.task_queue and docs_fetched_ref[0] < self.config.max_documents:
                task = session.task_queue.pop(0)
                source = sources_by_name.get(task.source)
                if source is None:
                    continue
                self._run_task_page(
                    source=source,
                    task=task,
                    session=session,
                    storage=storage,
                    seen_doc_ids=seen_doc_ids,
                    docs_fetched_ref=docs_fetched_ref,
                    errors=errors,
                )
                session.stats.tasks_remaining = len(session.task_queue)
                self._save_session(session)

            duration = time.time() - started
            self.emitter.emit(
                ProgressEvent(
                    stage="done",
                    current=docs_fetched_ref[0],
                    total=self.config.max_documents,
                    message=f"Fetched {docs_fetched_ref[0]} documents",
                )
            )

            session.status = "completed"
            session.stats.docs_collected = docs_fetched_ref[0]
            self._save_session(session)

            succeeded = True
            return FetchResult(
                session_id=session_id,
                documents_fetched=docs_fetched_ref[0],
                duration_seconds=duration,
                errors=errors,
            )
        except Exception as e:
            if self.config.write_meta:
                self._write_meta(
                    session_id=session_id,
                    topic=topic,
                    status="failed",
                    config={
                        "sources": source_names,
                        "max_documents": int(self.config.max_documents),
                        "max_task_pages": int(self.config.max_task_pages),
                        "deep_comments": self.config.deep_comments,
                        "resume": bool(self.config.resume),
                    },
                    summary={
                        "documents_fetched": int(session.stats.docs_collected or 0),
                        "errors": len(errors),
                        "error": str(e),
                    },
                )
            raise
        finally:
            storage.close()
            if self.config.write_meta and succeeded:
                status = "completed" if not errors else "completed_with_errors"
                self._write_meta(
                    session_id=session_id,
                    topic=topic,
                    status=status,
                    config={
                        "sources": source_names,
                        "max_documents": int(self.config.max_documents),
                        "max_task_pages": int(self.config.max_task_pages),
                        "deep_comments": self.config.deep_comments,
                        "resume": bool(self.config.resume),
                    },
                    summary={
                        "documents_fetched": int(session.stats.docs_collected or 0),
                        "errors": len(errors),
                    },
                )

    def _run_task_page(
        self,
        *,
        source,
        task: SearchTask,
        session: SessionState,
        storage: Storage,
        seen_doc_ids: set[str],
        docs_fetched_ref: list[int],
        errors: list[str],
    ) -> None:
        if task.budget < 1:
            task.budget = max(1, int(self.config.max_task_pages))

        if task.task_id not in session.visited_tasks:
            session.visited_tasks.append(task.task_id)

        try:
            page = source.search(task)
            session.stats.iterations += 1
        except Exception as e:
            msg = f"{source.name}: search failed: {e}"
            errors.append(msg)
            self.emitter.emit(ErrorEvent(message=msg, source=source.name))
            session.stats.tasks_completed += 1
            return

        for ref in page.items:
            if docs_fetched_ref[0] >= self.config.max_documents:
                break
            if ref.ref_id in seen_doc_ids:
                continue

            try:
                doc: RawDocument = source.fetch(ref, deep_comments=self.config.deep_comments)
            except Exception as e:
                msg = f"{source.name}: fetch failed for {ref.ref_id}: {e}"
                errors.append(msg)
                self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                seen_doc_ids.add(ref.ref_id)
                session.visited_docs.append(ref.ref_id)
                continue

            try:
                storage.save_document(doc)
            except Exception as e:
                msg = f"{source.name}: storage failed for {ref.ref_id}: {e}"
                errors.append(msg)
                self.emitter.emit(ErrorEvent(message=msg, source=source.name))
                seen_doc_ids.add(ref.ref_id)
                session.visited_docs.append(ref.ref_id)
                continue

            seen_doc_ids.add(ref.ref_id)
            session.visited_docs.append(ref.ref_id)
            docs_fetched_ref[0] += 1
            session.stats.docs_collected = docs_fetched_ref[0]
            self._save_session(session)

            self.emitter.emit(
                DocumentEvent(doc_id=doc.doc_id, title=doc.title, source=source.name)
            )
            self.emitter.emit(
                ProgressEvent(
                    stage="fetch",
                    current=docs_fetched_ref[0],
                    total=self.config.max_documents,
                    message=f"{source.name}: {doc.title}",
                )
            )

        session.stats.tasks_completed += 1

        if (not page.exhausted) and page.next_cursor and (task.budget > 1):
            next_task = SearchTask(**{**task.model_dump(), "cursor": page.next_cursor, "budget": task.budget - 1})
            session.task_queue.append(next_task)

    def _load_or_create_session(self, *, topic: str) -> SessionState:
        manager = SessionManager(self.config.data_dir)
        if self.config.resume:
            if not self.config.session_id:
                raise SessionError("resume requires session_id")
            session = manager.load_session(self.config.session_id)
            if session is None:
                raise SessionError(f"Session {self.config.session_id} not found")
            session.status = "running"
            return session

        if self.config.session_id:
            session = SessionState(
                session_id=self.config.session_id,
                topic=topic,
                status="running",
                max_iterations=10_000,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            manager.save_session(session)
            return session

        session = manager.create_session(topic, max_iterations=10_000)
        return session

    def _save_session(self, session: SessionState) -> None:
        SessionManager(self.config.data_dir).save_session(session)

    def _write_meta(
        self,
        *,
        session_id: str,
        topic: str,
        status: str,
        config: dict,
        summary: dict | None = None,
    ) -> None:
        import json
        from pathlib import Path

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = Path(self.config.data_dir) / session_id / "meta.json"
        created_at = now
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(existing.get("created_at"), str):
                    created_at = existing["created_at"]
            except Exception:
                pass

        payload = {
            "kind": "fetch",
            "session_id": session_id,
            "topic": topic,
            "status": status,
            "created_at": created_at,
            "updated_at": now,
            "config": config,
        }
        if summary:
            payload.update(summary)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
