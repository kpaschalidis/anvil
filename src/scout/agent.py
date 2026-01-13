import logging
from typing import Callable

from scout.config import ScoutConfig
from scout.cost import CostTracker
from scout.filters import ContentFilter
from scout.models import (
    SessionState,
    SearchTask,
    DocumentRef,
    Event,
    ExtractionResult,
    Page,
    generate_id,
    utc_now,
)
from scout.storage import Storage
from scout.session import SessionManager
from scout.extract import Extractor
from scout.complexity import assess_complexity, ITERATION_BUDGETS
from scout.parallel import ParallelExecutor, SearchResult
from scout.sources.base import Source

logger = logging.getLogger(__name__)


class IngestionAgent:
    def __init__(
        self,
        session: SessionState,
        sources: list[Source],
        config: ScoutConfig,
    ):
        self.session = session
        self.sources = {s.name: s for s in sources}
        self.config = config
        self.cost_tracker = CostTracker()
        self.storage = Storage(session.session_id, config.data_dir)
        self.session_manager = SessionManager(config.data_dir)
        self.content_filter = ContentFilter(config.filter)
        self.extractor = Extractor(
            model=config.llm.extraction_model,
            prompt_version=config.llm.extraction_prompt_version,
            max_retries=3,
            cost_tracker=self.cost_tracker,
        )
        self.parallel_executor = ParallelExecutor(max_workers=config.parallel_workers)

    def run(self) -> None:
        logger.info(f"Starting ingestion for session {self.session.session_id}")
        logger.info(f"Topic: {self.session.topic}")

        if not self.session.complexity:
            complexity = assess_complexity(
                self.session.topic,
                self.config.llm.complexity_model,
                cost_tracker=self.cost_tracker,
            )
            self.session.complexity = complexity.value
            self.session.max_iterations = ITERATION_BUDGETS[complexity]
            logger.info(
                f"Complexity: {complexity.value}, Max iterations: {self.session.max_iterations}"
            )

        if not self.session.task_queue:
            self._seed_tasks()

        try:
            while self._should_continue():
                self._run_iteration()
                self._save_state()

            self._finalize()

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self._log_event("interrupted", decision="User pressed Ctrl+C")
            self.session.status = "paused"
            self._save_state()
            print(
                f"\nSession paused. Resume with: scout run --resume {self.session.session_id}"
            )

        except Exception as e:
            logger.error(f"Agent error: {e}")
            self._log_event("error", decision=str(e))
            self.session.status = "error"
            self._save_state()
            raise

    def _seed_tasks(self) -> None:
        logger.info("Seeding initial tasks")

        queries = self._generate_semantic_queries(self.session.topic)
        logger.info(f"Generated {len(queries)} semantic queries")

        for source_name, source in self.sources.items():
            try:
                adapted_tasks = source.adapt_queries(queries, self.session.topic)
                for task in adapted_tasks:
                    if task.task_id not in [t.task_id for t in self.session.task_queue]:
                        self.session.task_queue.append(task)
                logger.info(
                    f"Added {len(adapted_tasks)} adapted tasks from {source_name}"
                )
            except Exception as e:
                logger.warning(f"Failed to adapt queries for {source_name}: {e}")

        self._log_event(
            "tasks_seeded", output={"task_count": len(self.session.task_queue)}
        )
        logger.info(f"Seeded {len(self.session.task_queue)} initial tasks")

    def _generate_semantic_queries(self, topic: str) -> list[str]:
        queries = [
            topic,
            f"{topic} problems",
            f"{topic} frustrating",
            f"{topic} hate",
            f"{topic} alternative",
            f"why is {topic} so hard",
        ]
        return queries

    def _add_search_task(
        self,
        source: str,
        source_entity: str,
        mode: str,
        query: str | None = None,
        time_filter: str | None = None,
    ) -> None:
        task = SearchTask(
            task_id=generate_id(),
            source=source,
            source_entity=source_entity,
            mode=mode,
            query=query,
            time_filter=time_filter,
            budget=25,
        )
        self.session.task_queue.append(task)

    def _run_iteration(self) -> None:
        self.session.stats.iterations += 1
        iteration = self.session.stats.iterations
        logger.info(f"=== Iteration {iteration} ===")

        tasks_to_run = self._pick_tasks(self.config.parallel_workers)
        if not tasks_to_run:
            logger.info("No tasks to run")
            return

        self._log_event(
            "iteration_started",
            input={"iteration": iteration, "task_count": len(tasks_to_run)},
        )

        all_refs: list[tuple[SearchTask, DocumentRef]] = []

        tasks_by_source: dict[str, list[SearchTask]] = {}
        for task in tasks_to_run:
            tasks_by_source.setdefault(task.source, []).append(task)

        for source_name, source_tasks in tasks_by_source.items():
            source = self.sources.get(source_name)
            if not source:
                logger.warning(f"Unknown source: {source_name}")
                continue

            for task in source_tasks:
                self._log_event(
                    "task_started", input={"task_id": task.task_id, "query": task.query}
                )

            search_results = self.parallel_executor.execute_searches(
                source_tasks,
                lambda t: source.search(t),
            )

            for result in search_results:
                task = result.task
                page = result.page

                if result.success:
                    for ref in page.items:
                        if ref.ref_id not in self.session.visited_docs:
                            all_refs.append((task, ref))

                    if page.next_cursor and not page.exhausted:
                        continuation_task = SearchTask(
                            task_id=generate_id(),
                            source=task.source,
                            source_entity=task.source_entity,
                            mode=task.mode,
                            query=task.query,
                            sort=task.sort,
                            time_filter=task.time_filter,
                            cursor=page.next_cursor,
                            budget=task.budget,
                        )
                        self.session.task_queue.append(continuation_task)

                    self.session.visited_tasks.append(task.task_id)
                    self.session.stats.tasks_completed += 1
                    self._log_event(
                        "task_completed",
                        input={"task_id": task.task_id},
                        output={
                            "refs_found": len(page.items),
                            "exhausted": page.exhausted,
                        },
                    )
                else:
                    logger.error(f"Task {task.task_id} failed: {result.error}")
                    self._log_event(
                        "task_failed",
                        input={"task_id": task.task_id},
                        decision=result.error or "Unknown error",
                    )

        logger.info(f"Found {len(all_refs)} new refs to process")

        for task, ref in all_refs:
            if self.session.stats.docs_collected >= self.config.max_documents:
                logger.info("Max documents reached")
                break

            self._process_ref(task, ref)

        self.session.stats.tasks_remaining = len(self.session.task_queue)

    def _pick_tasks(self, count: int) -> list[SearchTask]:
        tasks: list[SearchTask] = []
        while len(tasks) < count and self.session.task_queue:
            task = self.session.task_queue.pop(0)
            if task.task_id not in self.session.visited_tasks:
                tasks.append(task)
        return tasks

    def _process_ref(self, task: SearchTask, ref: DocumentRef) -> None:
        if ref.ref_id in self.session.visited_docs:
            return

        source = self.sources.get(task.source)
        if not source:
            return

        try:
            doc = source.fetch(ref, deep_comments=self.config.deep_comments)

            self.storage.save_document(doc)
            self.session.visited_docs.append(ref.ref_id)
            self.session.stats.docs_collected += 1

            logger.info(f"Saved document {doc.doc_id}: {doc.title[:50]}...")

            should_extract, reason = self.content_filter.should_extract(doc)
            if not should_extract:
                self._log_event(
                    "doc_filtered",
                    input={"doc_id": doc.doc_id},
                    decision=reason,
                    metrics={"raw_text_len": len(doc.raw_text)},
                )
                return

            try:
                result = self.extractor.extract(
                    doc,
                    self.session.topic,
                    self.session.knowledge,
                )

                for snippet in result.snippets:
                    self.storage.save_snippet(snippet)
                    self.session.stats.snippets_extracted += 1

                self.session.knowledge.extend(
                    [s.pain_statement for s in result.snippets]
                )

                self._add_follow_up_tasks(result, task.source)

                self.session.novelty_history.append(result.novelty)

                self._log_event(
                    "extraction_done",
                    input={"doc_id": doc.doc_id},
                    output={
                        "snippets": len(result.snippets),
                        "entities": len(result.entities),
                        "novelty": result.novelty,
                    },
                )

            except Exception as e:
                logger.error(f"Extraction failed for {doc.doc_id}: {e}")
                self._log_event(
                    "extraction_failed", input={"doc_id": doc.doc_id}, decision=str(e)
                )

        except Exception as e:
            logger.error(f"Failed to fetch {ref.ref_id}: {e}")
            self._log_event(
                "fetch_failed", input={"ref_id": ref.ref_id}, decision=str(e)
            )

    def _add_follow_up_tasks(self, result: ExtractionResult, source: str) -> None:
        for entity in result.entities[:3]:
            if not self._task_exists(f"{entity} problems"):
                self._add_search_task(
                    source, "all", "search", query=f"{entity} problems"
                )

        for query in result.follow_up_queries[:2]:
            if not self._task_exists(query):
                self._add_search_task(source, "all", "search", query=query)

    def _task_exists(self, query: str) -> bool:
        query_lower = query.lower()
        for task in self.session.task_queue:
            if task.query and task.query.lower() == query_lower:
                return True
        return False

    def _should_continue(self) -> bool:
        if (
            self.config.max_cost_usd is not None
            and self.session.stats.total_cost_usd >= self.config.max_cost_usd
        ):
            logger.info("Stop: Max cost reached")
            self._log_event(
                "stop",
                decision="Max cost reached",
                metrics={"total_cost_usd": self.session.stats.total_cost_usd},
            )
            return False

        if not self.session.task_queue:
            logger.info("Stop: Task queue empty")
            self._log_event("stop", decision="Task queue empty")
            return False

        if self.session.stats.iterations >= self.session.max_iterations:
            logger.info("Stop: Max iterations reached")
            self._log_event("stop", decision="Max iterations reached")
            return False

        if self.session.stats.docs_collected >= self.config.max_documents:
            logger.info("Stop: Max documents reached")
            self._log_event("stop", decision="Max documents reached")
            return False

        if self._is_saturated():
            logger.info("Stop: Saturation detected")
            self._log_event(
                "stop",
                decision="Saturation detected",
                metrics={"avg_novelty": self._avg_novelty()},
            )
            return False

        return True

    def _is_saturated(self) -> bool:
        if len(self.session.novelty_history) < self.config.saturation_window:
            return False

        avg = self._avg_novelty()
        return avg < self.config.saturation_threshold

    def _avg_novelty(self) -> float:
        if not self.session.novelty_history:
            return 1.0
        recent = self.session.novelty_history[-self.config.saturation_window :]
        return sum(recent) / len(recent)

    def _finalize(self) -> None:
        self.session.status = "completed"
        self.session.stats.avg_novelty = self._avg_novelty()
        self._save_state()

        logger.info("=== Session Complete ===")
        logger.info(f"Documents collected: {self.session.stats.docs_collected}")
        logger.info(f"Snippets extracted: {self.session.stats.snippets_extracted}")
        logger.info(f"Iterations: {self.session.stats.iterations}")
        logger.info(f"Avg novelty: {self.session.stats.avg_novelty:.2f}")

    def _save_state(self) -> None:
        totals = self.cost_tracker.totals()
        self.session.stats.total_tokens = totals.total_tokens
        self.session.stats.total_cost_usd = totals.total_cost_usd
        self.session.stats.llm_calls = totals.calls
        self.session.stats.extraction_calls = totals.calls_by_kind.get("extraction", 0)
        self.session.stats.complexity_calls = totals.calls_by_kind.get("complexity", 0)
        self.session_manager.save_session(self.session)

    def _log_event(
        self,
        kind: str,
        input: dict | None = None,
        output: dict | None = None,
        decision: str = "",
        metrics: dict | None = None,
    ) -> None:
        event = Event(
            event_id=generate_id(),
            session_id=self.session.session_id,
            ts=utc_now(),
            kind=kind,
            input=input or {},
            output=output or {},
            decision=decision,
            metrics=metrics or {},
        )
        self.storage.log_event(event)
