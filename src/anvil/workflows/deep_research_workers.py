from __future__ import annotations

from urllib.parse import urlparse

from common.events import ProgressEvent, WorkerCompletedEvent

from anvil.subagents.parallel import WorkerResult, WorkerTask


class DeepResearchWorkersMixin:
    def _run_round(
        self,
        *,
        stage_label: str,
        message: str,
        tasks: list[WorkerTask],
    ) -> list[WorkerResult]:
        if not tasks:
            return []

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage=stage_label, current=0, total=len(tasks), message=message))

        results = self.parallel_runner.spawn_parallel(
            tasks,
            max_workers=self.config.max_workers,
            timeout=self.config.worker_timeout_s,
            allow_writes=False,
            max_web_search_calls=max(1, int(self.config.max_web_search_calls)),
            max_web_extract_calls=(max(0, int(self.config.max_web_extract_calls)) if self.config.enable_deep_read else 0),
            extract_max_chars=int(self.config.extract_max_chars),
            on_result=(self._emit_worker_completed if self.emitter is not None else None),
        )
        results = self._apply_worker_invariants(results)

        if self.config.best_effort:
            return results

        max_attempts = max(1, int(self.config.worker_max_attempts))
        if max_attempts <= 1:
            return results

        failed_ids = {r.task_id for r in results if not r.success}
        if not failed_ids:
            return results

        if self.emitter is not None:
            self.emitter.emit(
                ProgressEvent(
                    stage=stage_label,
                    current=0,
                    total=len(failed_ids),
                    message=f"Retrying {len(failed_ids)} failed task(s)",
                )
            )

        retry_tasks = [t for t in tasks if t.id in failed_ids]
        if not retry_tasks:
            return results

        rerun = self.parallel_runner.spawn_parallel(
            retry_tasks,
            max_workers=self.config.max_workers,
            timeout=self.config.worker_timeout_s,
            allow_writes=False,
            max_web_search_calls=max(1, int(self.config.max_web_search_calls)),
            max_web_extract_calls=(max(0, int(self.config.max_web_extract_calls)) if self.config.enable_deep_read else 0),
            extract_max_chars=int(self.config.extract_max_chars),
            on_result=(self._emit_worker_completed if self.emitter is not None else None),
        )
        rerun = self._apply_worker_invariants(rerun)

        by_id = {r.task_id: r for r in results}
        for r in rerun:
            by_id[r.task_id] = r
        return [by_id.get(t.id, by_id.get(t.id) or WorkerResult(task_id=t.id, success=False)) for t in tasks]

    def _emit_worker_completed(self, result: WorkerResult) -> None:
        if self.emitter is None:
            return
        urls = set(getattr(result, "citations", ()) or ())
        domains = {urlparse(u).netloc for u in urls if isinstance(u, str) and u.startswith("http")}
        evidence = getattr(result, "evidence", ()) or ()
        self.emitter.emit(
            WorkerCompletedEvent(
                task_id=str(getattr(result, "task_id", "") or ""),
                success=bool(getattr(result, "success", False)),
                web_search_calls=int(getattr(result, "web_search_calls", 0) or 0),
                web_extract_calls=int(getattr(result, "web_extract_calls", 0) or 0),
                citations=len(urls),
                domains=len(domains),
                evidence=len(evidence) if isinstance(evidence, (list, tuple)) else 0,
                duration_ms=getattr(result, "duration_ms", None),
                error=str(getattr(result, "error", "") or ""),
            )
        )

    def _format_worker_diagnostics(self, results) -> str:
        lines: list[str] = []
        for r in results:
            lines.append(
                f"- {r.task_id}: success={r.success} web_search_calls={getattr(r, 'web_search_calls', 0)} citations={len(getattr(r, 'citations', ()) or ())} error={r.error or ''}".rstrip()
            )
        return "\n".join(lines) if lines else "(no workers)"

    def _apply_worker_invariants(self, results):
        updated = []
        for r in results:
            if not r.success:
                updated.append(r)
                continue
            if self.config.enable_deep_read and len(getattr(r, "evidence", ()) or ()) < 1:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        sources=getattr(r, "sources", {}) or {},
                        web_search_calls=r.web_search_calls,
                        web_search_trace=getattr(r, "web_search_trace", ()) or (),
                        web_extract_calls=int(getattr(r, "web_extract_calls", 0) or 0),
                        web_extract_trace=getattr(r, "web_extract_trace", ()) or (),
                        evidence=getattr(r, "evidence", ()) or (),
                        iterations=int(getattr(r, "iterations", 0) or 0),
                        duration_ms=getattr(r, "duration_ms", None),
                        success=False,
                        error="Worker collected no extracted evidence (web_extract)",
                    )
                )
                continue
            if len(getattr(r, "citations", ()) or ()) < 1 and not self.config.enable_deep_read:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        sources=getattr(r, "sources", {}) or {},
                        web_search_calls=r.web_search_calls,
                        web_search_trace=getattr(r, "web_search_trace", ()) or (),
                        web_extract_calls=int(getattr(r, "web_extract_calls", 0) or 0),
                        web_extract_trace=getattr(r, "web_extract_trace", ()) or (),
                        evidence=getattr(r, "evidence", ()) or (),
                        iterations=int(getattr(r, "iterations", 0) or 0),
                        duration_ms=getattr(r, "duration_ms", None),
                        success=False,
                        error="Worker collected no citations",
                    )
                )
                continue
            updated.append(r)
        return updated
