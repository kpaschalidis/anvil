from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from anvil.subagents.task_tool import SubagentRunner


WORKER_SAFE_TOOLS: set[str] = {"read_file", "grep", "list_files"}


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
    ) -> list[WorkerResult]:
        if not tasks:
            return []

        allowed_tool_names = None if allow_writes else WORKER_SAFE_TOOLS

        results: list[WorkerResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.runner.run_task,
                    prompt=task.prompt,
                    agent_name=task.agent_name,
                    max_iterations=task.max_iterations,
                    allowed_tool_names=allowed_tool_names,
                ): task
                for task in tasks
            }

            for future in as_completed(futures, timeout=timeout):
                task = futures[future]
                try:
                    output = future.result()
                    results.append(
                        WorkerResult(task_id=task.id, output=output or "", success=True)
                    )
                except Exception as e:
                    results.append(
                        WorkerResult(task_id=task.id, success=False, error=str(e))
                    )

        return results

