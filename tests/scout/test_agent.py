import pytest
from unittest.mock import patch, MagicMock

from scout.parallel import ParallelExecutor, SearchResult, SuccessRateTracker
from scout.circuit_breaker import CircuitBreaker
from scout.models import SearchTask, Page, DocumentRef, generate_id
from scout.progress import ProgressInfo


class TestSuccessRateTracker:
    def test_empty_returns_full_rate(self):
        tracker = SuccessRateTracker()
        assert tracker.rate() == 1.0

    def test_all_success(self):
        tracker = SuccessRateTracker(window=5)
        for _ in range(5):
            tracker.record(True)
        assert tracker.rate() == 1.0

    def test_all_failure(self):
        tracker = SuccessRateTracker(window=5)
        for _ in range(5):
            tracker.record(False)
        assert tracker.rate() == 0.0

    def test_mixed_results(self):
        tracker = SuccessRateTracker(window=10)
        for _ in range(7):
            tracker.record(True)
        for _ in range(3):
            tracker.record(False)
        assert tracker.rate() == pytest.approx(0.7)

    def test_window_eviction(self):
        tracker = SuccessRateTracker(window=3)
        tracker.record(False)
        tracker.record(False)
        tracker.record(False)
        assert tracker.rate() == 0.0
        tracker.record(True)
        tracker.record(True)
        tracker.record(True)
        assert tracker.rate() == 1.0


class TestParallelExecutorAdaptiveScaling:
    def test_scales_down_on_low_success_rate(self):
        executor = ParallelExecutor(max_workers=8, adaptive_scaling=True)
        for _ in range(10):
            executor.success_tracker.record(False)
        effective = executor._effective_workers(8)
        assert effective == 4

    def test_no_scaling_when_disabled(self):
        executor = ParallelExecutor(max_workers=8, adaptive_scaling=False)
        for _ in range(10):
            executor.success_tracker.record(False)
        effective = executor._effective_workers(8)
        assert effective == 8

    def test_maintains_workers_on_high_success_rate(self):
        executor = ParallelExecutor(max_workers=8, adaptive_scaling=True)
        for _ in range(10):
            executor.success_tracker.record(True)
        effective = executor._effective_workers(8)
        assert effective == 8

    def test_minimum_one_worker(self):
        executor = ParallelExecutor(max_workers=2, adaptive_scaling=True)
        for _ in range(20):
            executor.success_tracker.record(False)
        effective = executor._effective_workers(2)
        assert effective == 1


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.can_execute() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is True
        cb.record_failure()
        assert cb.can_execute() is False

    def test_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is True

    def test_recovers_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is False
        import time

        time.sleep(0.02)
        assert cb.can_execute() is True

    def test_closes_on_success_after_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.01)
        cb.record_failure()
        cb.record_failure()
        import time

        time.sleep(0.02)
        assert cb.can_execute() is True
        cb.record_success()
        assert cb.state() == "closed"


class TestProgressInfo:
    def test_progress_info_fields(self):
        info = ProgressInfo(
            iteration=5,
            max_iterations=10,
            docs_collected=25,
            max_documents=100,
            snippets_extracted=50,
            tasks_remaining=15,
            avg_novelty=0.7,
            total_cost_usd=0.25,
        )
        assert info.iteration == 5
        assert info.max_iterations == 10
        assert info.docs_collected == 25
        assert info.snippets_extracted == 50
        assert info.avg_novelty == pytest.approx(0.7)
        assert info.total_cost_usd == pytest.approx(0.25)


class TestParallelExecutorExecution:
    def test_returns_empty_for_no_tasks(self):
        executor = ParallelExecutor()
        results = executor.execute_searches([], lambda t: Page(items=[]))
        assert results == []

    def test_executes_tasks_and_returns_results(self):
        executor = ParallelExecutor(max_workers=2)

        def search_fn(task: SearchTask) -> Page[DocumentRef]:
            return Page(
                items=[
                    DocumentRef(
                        ref_id=f"ref:{task.task_id}:0",
                        ref_type="post",
                        source="test",
                        source_entity="all",
                        discovered_from_task_id=task.task_id,
                    )
                ],
                exhausted=True,
            )

        tasks = [
            SearchTask(source="test", source_entity="all", mode="search", query="q1"),
            SearchTask(source="test", source_entity="all", mode="search", query="q2"),
        ]
        results = executor.execute_searches(tasks, search_fn)
        assert len(results) == 2
        assert all(r.success for r in results)
        assert all(len(r.page.items) == 1 for r in results)

    def test_handles_task_exception(self):
        executor = ParallelExecutor(max_workers=1, max_retries=0)

        def failing_search(task: SearchTask) -> Page[DocumentRef]:
            raise ValueError("Search failed")

        tasks = [
            SearchTask(source="test", source_entity="all", mode="search", query="q")
        ]
        results = executor.execute_searches(tasks, failing_search)
        assert len(results) == 1
        assert results[0].success is False
        assert "Search failed" in (results[0].error or "")

    def test_tracks_duration_ms(self):
        executor = ParallelExecutor(max_workers=1)

        def slow_search(task: SearchTask) -> Page[DocumentRef]:
            import time

            time.sleep(0.05)
            return Page(items=[], exhausted=True)

        tasks = [
            SearchTask(source="test", source_entity="all", mode="search", query="q")
        ]
        results = executor.execute_searches(tasks, slow_search)
        assert results[0].duration_ms is not None
        assert results[0].duration_ms >= 50
