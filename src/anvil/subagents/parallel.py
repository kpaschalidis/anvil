from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from anvil.subagents.task_tool import SubagentRunner


WORKER_SAFE_TOOLS: set[str] = {"read_file", "grep", "list_files", "web_search"}


@dataclass(frozen=True, slots=True)
class WorkerTask:
    id: str
    prompt: str
    agent_name: str | None = None
    max_iterations: int = 6


@dataclass(frozen=True, slots=True)
class WorkerResult:
    task_id: str
    output: str = ""
    citations: tuple[str, ...] = ()
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    web_search_calls: int = 0
    success: bool = True
    error: str | None = None


class ParallelWorkerRunner:
    def __init__(self, runner: SubagentRunner):
        self.runner = runner

    def spawn_parallel(
        self,
        tasks: list[WorkerTask],
        *,
        max_workers: int = 5,
        timeout: float | None = 60.0,
        allow_writes: bool = False,
        max_web_search_calls: int | None = None,
    ) -> list[WorkerResult]:
        if not tasks:
            return []

        allowed_tool_names = None if allow_writes else WORKER_SAFE_TOOLS

        results: list[WorkerResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            run_kwargs = {"allowed_tool_names": allowed_tool_names}
            if max_web_search_calls is not None:
                run_kwargs["max_web_search_calls"] = max_web_search_calls
            futures = {
                executor.submit(
                    self.runner.run_task_with_trace,
                    prompt=task.prompt,
                    agent_name=task.agent_name,
                    max_iterations=task.max_iterations,
                    **run_kwargs,
                ): task
                for task in tasks
            }

            for future in as_completed(futures, timeout=timeout):
                task = futures[future]
                try:
                    output, trace = future.result()
                    results.append(
                        WorkerResult(
                            task_id=task.id,
                            output=output or "",
                            citations=tuple(sorted(trace.citations)),
                            sources=dict(getattr(trace, "sources", {}) or {}),
                            web_search_calls=int(trace.web_search_calls or 0),
                            success=True,
                        )
                    )
                except Exception as e:
                    results.append(
                        WorkerResult(task_id=task.id, success=False, error=str(e))
                    )

        return results
