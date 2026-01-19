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

        results = self._maybe_continue_workers(
            tasks,
            results,
            stage_label=stage_label,
            message_prefix=f"Continuing {stage_label} tasks",
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

    def _continuation_prompt(
        self,
        *,
        base_prompt: str,
        prior_output: str,
        prior_citations: list[str],
        prior_evidence_urls: list[str],
        additional_calls: int,
        remaining_extracts: int,
    ) -> str:
        prior = "\n".join(f"- {u}" for u in prior_citations[:15])
        extra = max(1, int(additional_calls))
        extract_block = ""
        if bool(self.config.enable_deep_read) and int(remaining_extracts) > 0:
            already_read = "\n".join(f"- {u}" for u in prior_evidence_urls[:15])
            extract_block = (
                "\n"
                + f"After searching, call `web_extract` on up to {int(remaining_extracts)} NEW URLs (pages you have not extracted yet).\n"
                + f"Use `max_chars={max(1, int(self.config.extract_max_chars))}`.\n"
                + "Prefer diverse, reputable domains and avoid duplicates.\n"
                + "Already extracted URLs (do not re-extract):\n"
                + (already_read if already_read else "(none)")
                + "\n"
            )
        return (
            base_prompt.strip()
            + "\n\n"
            + "Continue researching this same task.\n"
            + f"Make ~{extra} additional `web_search` calls (if possible), focusing on NEW domains and NEW query variants.\n"
            + f"Use pagination (page=1..{max(1, int(self.config.max_pages))}) and page_size={max(1, int(self.config.page_size))}.\n"
            + "Avoid reusing URLs you already collected.\n\n"
            + "Already collected URLs (do not reuse):\n"
            + (prior if prior else "(none)")
            + (extract_block if extract_block else "")
            + "\n\n"
            + "Append new bullet points and cite any new URLs you used.\n"
            + (f"\n\nPrevious notes:\n{prior_output.strip()}" if (prior_output or "").strip() else "")
        )

    def _merge_worker_results(self, a: WorkerResult, b: WorkerResult) -> WorkerResult:
        citations = tuple(sorted(set(a.citations or ()) | set(b.citations or ())))
        sources = dict(getattr(a, "sources", {}) or {})
        sources.update(dict(getattr(b, "sources", {}) or {}))
        trace = tuple((getattr(a, "web_search_trace", ()) or ()) + (getattr(b, "web_search_trace", ()) or ()))
        extract_trace = tuple((getattr(a, "web_extract_trace", ()) or ()) + (getattr(b, "web_extract_trace", ()) or ()))
        evidence = tuple((getattr(a, "evidence", ()) or ()) + (getattr(b, "evidence", ()) or ()))
        output_parts = []
        if (a.output or "").strip():
            output_parts.append(a.output.strip())
        if (b.output or "").strip():
            output_parts.append(b.output.strip())
        duration_ms = None
        if getattr(a, "duration_ms", None) is not None or getattr(b, "duration_ms", None) is not None:
            duration_ms = int((getattr(a, "duration_ms", 0) or 0) + (getattr(b, "duration_ms", 0) or 0))
        return WorkerResult(
            task_id=a.task_id,
            output="\n\n".join(output_parts),
            citations=citations,
            sources=sources,
            web_search_calls=int(getattr(a, "web_search_calls", 0) or 0) + int(getattr(b, "web_search_calls", 0) or 0),
            web_search_trace=trace,
            web_extract_calls=int(getattr(a, "web_extract_calls", 0) or 0) + int(getattr(b, "web_extract_calls", 0) or 0),
            web_extract_trace=extract_trace,
            evidence=evidence,
            iterations=int(getattr(a, "iterations", 0) or 0) + int(getattr(b, "iterations", 0) or 0),
            duration_ms=duration_ms,
            success=a.success and b.success,
            error=a.error or b.error,
        )

    def _maybe_continue_workers(
        self,
        tasks: list[WorkerTask],
        results: list[WorkerResult],
        *,
        stage_label: str,
        message_prefix: str,
    ) -> list[WorkerResult]:
        if not self.config.enable_worker_continuation:
            return results

        if self.config.best_effort:
            return results
        target = max(1, int(self.config.target_web_search_calls))
        if target <= 1:
            return results
        max_total = max(1, int(self.config.max_web_search_calls))
        max_total_extract = max(0, int(self.config.max_web_extract_calls)) if bool(self.config.enable_deep_read) else 0
        max_rounds = max(0, int(self.config.max_worker_continuations))
        if max_rounds <= 0:
            return results

        task_by_id = {t.id: t for t in tasks}
        results_by_id = {r.task_id: r for r in results}

        for _ in range(max_rounds):
            todo: list[WorkerTask] = []
            for r in results_by_id.values():
                if not r.success:
                    continue
                current_calls = int(getattr(r, "web_search_calls", 0) or 0)
                remaining = max_total - current_calls
                need = target - current_calls
                if need <= 0 or remaining <= 0:
                    continue
                t = task_by_id.get(r.task_id)
                if t is None:
                    continue
                current_extract = int(getattr(r, "web_extract_calls", 0) or 0)
                remaining_extract = max(0, max_total_extract - current_extract)
                prompt = self._continuation_prompt(
                    base_prompt=t.prompt,
                    prior_output=r.output,
                    prior_citations=list(getattr(r, "citations", ()) or ()),
                    prior_evidence_urls=[
                        str(ev.get("url"))
                        for ev in (getattr(r, "evidence", ()) or ())
                        if isinstance(ev, dict) and isinstance(ev.get("url"), str)
                    ],
                    additional_calls=min(need, remaining),
                    remaining_extracts=remaining_extract,
                )
                todo.append(
                    WorkerTask(
                        id=r.task_id,
                        prompt=prompt,
                        agent_name=t.agent_name,
                        max_iterations=t.max_iterations,
                        max_web_search_calls=remaining,
                        max_web_extract_calls=remaining_extract,
                    )
                )

            if not todo:
                break

            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(
                        stage=stage_label,
                        current=0,
                        total=len(todo),
                        message=f"{message_prefix}: {len(todo)} task(s)",
                    )
                )

            more = self.parallel_runner.spawn_parallel(
                todo,
                max_workers=self.config.max_workers,
                timeout=self.config.worker_timeout_s,
                allow_writes=False,
                max_web_search_calls=None,
                max_web_extract_calls=max_total_extract,
                extract_max_chars=int(self.config.extract_max_chars),
                on_result=(self._emit_worker_completed if self.emitter is not None else None),
            )
            for nr in more:
                prev = results_by_id.get(nr.task_id)
                if prev is None:
                    results_by_id[nr.task_id] = nr
                    continue
                if not nr.success:
                    continue
                results_by_id[nr.task_id] = self._merge_worker_results(prev, nr)

        ordered: list[WorkerResult] = []
        for r in results:
            ordered.append(results_by_id.get(r.task_id, r))
        return ordered

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

