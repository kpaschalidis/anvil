import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

logger = logging.getLogger(__name__)

SUCCESS_RATE_WINDOW = 20
LOW_SUCCESS_RATE_THRESHOLD = 0.5

TaskT = TypeVar("TaskT")
PageT = TypeVar("PageT")


@dataclass
class SearchResult(Generic[TaskT, PageT]):
    task: TaskT
    page: PageT
    success: bool
    error: str | None = None
    duration_ms: int | None = None


class SuccessRateTracker:
    def __init__(self, window: int = SUCCESS_RATE_WINDOW):
        self.window = window
        self._history: deque[bool] = deque(maxlen=window)

    def record(self, success: bool) -> None:
        self._history.append(success)

    def rate(self) -> float:
        if not self._history:
            return 1.0
        return sum(self._history) / len(self._history)


class ParallelExecutor(Generic[TaskT, PageT]):
    def __init__(
        self,
        max_workers: int = 5,
        *,
        overall_timeout: float = 60.0,
        task_timeout: float = 30.0,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        adaptive_scaling: bool = True,
    ):
        self.max_workers = max_workers
        self.overall_timeout = overall_timeout
        self.task_timeout = task_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.adaptive_scaling = adaptive_scaling
        self.success_tracker = SuccessRateTracker()

    def _effective_workers(self, task_count: int) -> int:
        base = min(self.max_workers, task_count)
        if not self.adaptive_scaling:
            return base
        rate = self.success_tracker.rate()
        if rate < LOW_SUCCESS_RATE_THRESHOLD:
            scaled = max(1, base // 2)
            logger.info(
                f"Scaling down workers: {base} -> {scaled} (success rate {rate:.2f})"
            )
            return scaled
        return base

    def execute(
        self,
        tasks: list[TaskT],
        fn: Callable[[TaskT], PageT],
        *,
        empty_page: Callable[[], PageT],
    ) -> list[SearchResult[TaskT, PageT]]:
        if not tasks:
            return []

        results: list[SearchResult[TaskT, PageT]] = []
        actual_workers = self._effective_workers(len(tasks))

        logger.info(f"Executing {len(tasks)} tasks with {actual_workers} workers")

        if actual_workers <= 1:
            for task in tasks:
                start = time.monotonic()
                try:
                    page = self._safe_call(fn, task)
                    duration_ms = int((time.monotonic() - start) * 1000)
                    results.append(
                        SearchResult(task=task, page=page, success=True, duration_ms=duration_ms)
                    )
                    self.success_tracker.record(True)
                except Exception as e:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    results.append(
                        SearchResult(
                            task=task,
                            page=empty_page(),
                            success=False,
                            error=str(e),
                            duration_ms=duration_ms,
                        )
                    )
                    self.success_tracker.record(False)
            return results

        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            starts = {id(task): time.monotonic() for task in tasks}
            future_to_task = {executor.submit(self._safe_call, fn, task): task for task in tasks}

            try:
                for future in as_completed(future_to_task, timeout=self.overall_timeout):
                    task = future_to_task[future]
                    duration_ms = int((time.monotonic() - starts.get(id(task), 0.0)) * 1000)
                    try:
                        page = future.result(timeout=self.task_timeout)
                        results.append(
                            SearchResult(task=task, page=page, success=True, duration_ms=duration_ms)
                        )
                        self.success_tracker.record(True)
                    except TimeoutError:
                        results.append(
                            SearchResult(
                                task=task,
                                page=empty_page(),
                                success=False,
                                error="Timeout",
                                duration_ms=duration_ms,
                            )
                        )
                        self.success_tracker.record(False)
                    except Exception as e:
                        results.append(
                            SearchResult(
                                task=task,
                                page=empty_page(),
                                success=False,
                                error=str(e),
                                duration_ms=duration_ms,
                            )
                        )
                        self.success_tracker.record(False)
            except TimeoutError:
                logger.error("Overall parallel execution timed out")
                for task in tasks:
                    if not any(r.task is task for r in results):
                        results.append(
                            SearchResult(
                                task=task,
                                page=empty_page(),
                                success=False,
                                error="Overall timeout",
                                duration_ms=None,
                            )
                        )

        return results

    def _safe_call(self, fn: Callable[[TaskT], PageT], task: TaskT) -> PageT:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(task)
            except Exception as e:
                last_error = e
                if attempt == self.max_retries:
                    raise
                time.sleep(self.retry_delay)
        raise last_error or RuntimeError("Task failed without exception")

