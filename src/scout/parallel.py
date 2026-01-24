from __future__ import annotations

from typing import Callable

from common.parallel import (
    LOW_SUCCESS_RATE_THRESHOLD,
    SUCCESS_RATE_WINDOW,
    ParallelExecutor as _ParallelExecutor,
    SearchResult as _SearchResult,
    SuccessRateTracker,
)
from scout.models import DocumentRef, Page, SearchTask


SearchResult = _SearchResult[SearchTask, Page[DocumentRef]]


class ParallelExecutor:
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
        self._exec: _ParallelExecutor[SearchTask, Page[DocumentRef]] = _ParallelExecutor(
            max_workers=max_workers,
            overall_timeout=overall_timeout,
            task_timeout=task_timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            adaptive_scaling=adaptive_scaling,
        )
        self.success_tracker = self._exec.success_tracker

    def execute_searches(
        self,
        tasks: list[SearchTask],
        search_fn: Callable[[SearchTask], Page[DocumentRef]],
    ) -> list[SearchResult]:
        return self._exec.execute(
            tasks,
            search_fn,
            empty_page=lambda: Page(items=[], exhausted=True),
        )

    def _effective_workers(self, task_count: int) -> int:
        return self._exec._effective_workers(task_count)


__all__ = [
    "SUCCESS_RATE_WINDOW",
    "LOW_SUCCESS_RATE_THRESHOLD",
    "SearchResult",
    "SuccessRateTracker",
    "ParallelExecutor",
]
