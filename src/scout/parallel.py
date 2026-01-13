import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass
import time
from typing import Callable

from scout.models import SearchTask, DocumentRef, Page

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    task: SearchTask
    page: Page[DocumentRef]
    success: bool
    error: str | None = None
    duration_ms: int | None = None


class ParallelExecutor:
    def __init__(
        self,
        max_workers: int = 5,
        *,
        overall_timeout: float = 60.0,
        task_timeout: float = 30.0,
        max_retries: int = 0,
        retry_delay: float = 1.0,
    ):
        self.max_workers = max_workers
        self.overall_timeout = overall_timeout
        self.task_timeout = task_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def execute_searches(
        self,
        tasks: list[SearchTask],
        search_fn: Callable[[SearchTask], Page[DocumentRef]],
    ) -> list[SearchResult]:
        if not tasks:
            return []

        results: list[SearchResult] = []
        actual_workers = min(self.max_workers, len(tasks))

        logger.info(
            f"Executing {len(tasks)} search tasks with {actual_workers} workers"
        )

        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            starts = {t.task_id: time.monotonic() for t in tasks}
            future_to_task = {
                executor.submit(self._safe_search, search_fn, task): task
                for task in tasks
            }

            try:
                for future in as_completed(
                    future_to_task, timeout=self.overall_timeout
                ):
                    task = future_to_task[future]
                    duration_ms = int(
                        (time.monotonic() - starts.get(task.task_id, 0.0)) * 1000
                    )
                    try:
                        page = future.result(timeout=self.task_timeout)
                        results.append(
                            SearchResult(
                                task=task,
                                page=page,
                                success=True,
                                duration_ms=duration_ms,
                            )
                        )
                        logger.info(
                            f"Task {task.task_id} returned {len(page.items)} results"
                        )
                    except TimeoutError:
                        logger.error(f"Task {task.task_id} timed out")
                        results.append(
                            SearchResult(
                                task=task,
                                page=Page(items=[], exhausted=True),
                                success=False,
                                error="Timeout",
                                duration_ms=duration_ms,
                            )
                        )
                    except Exception as e:
                        logger.error(f"Task {task.task_id} failed: {e}")
                        results.append(
                            SearchResult(
                                task=task,
                                page=Page(items=[], exhausted=True),
                                success=False,
                                error=str(e),
                                duration_ms=duration_ms,
                            )
                        )
            except TimeoutError:
                logger.error("Overall parallel execution timed out")
                for task in tasks:
                    if not any(r.task.task_id == task.task_id for r in results):
                        results.append(
                            SearchResult(
                                task=task,
                                page=Page(items=[], exhausted=True),
                                success=False,
                                error="Overall timeout",
                                duration_ms=None,
                            )
                        )

        total_refs = sum(len(r.page.items) for r in results)
        success_count = sum(1 for r in results if r.success)
        logger.info(
            f"Parallel execution complete: {total_refs} refs from {success_count}/{len(tasks)} successful tasks"
        )
        return results

    def _safe_search(
        self,
        search_fn: Callable[[SearchTask], Page[DocumentRef]],
        task: SearchTask,
    ) -> Page[DocumentRef]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return search_fn(task)
            except Exception as e:
                last_error = e
                if attempt == self.max_retries:
                    logger.error(f"Search error in task {task.task_id}: {e}")
                    raise
                time.sleep(self.retry_delay)
        raise last_error or RuntimeError("Search failed without exception")
