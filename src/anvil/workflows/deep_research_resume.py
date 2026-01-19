from __future__ import annotations

import json
from pathlib import Path

from anvil.subagents.parallel import WorkerResult
from anvil.workflows.deep_research import DeepResearchOutcome, DeepResearchWorkflow
from anvil.workflows.iterative_loop import detect_report_type


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_existing_worker_results(workers_dir: Path) -> dict[str, WorkerResult]:
    results: dict[str, WorkerResult] = {}
    if not workers_dir.exists():
        return results
    for p in workers_dir.glob("*.json"):
        try:
            payload = _load_json(p)
        except Exception:
            continue
        task_id = str(payload.get("task_id") or p.stem)
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            sources = {}
        results[task_id] = WorkerResult(
            task_id=task_id,
            output=str(payload.get("output") or ""),
            citations=tuple(payload.get("citations") or ()),
            sources={k: v for k, v in sources.items() if isinstance(k, str) and isinstance(v, dict)},
            web_search_calls=int(payload.get("web_search_calls") or 0),
            web_search_trace=tuple(payload.get("web_search_trace") or ()),
            web_extract_calls=int(payload.get("web_extract_calls") or 0),
            web_extract_trace=tuple(payload.get("web_extract_trace") or ()),
            evidence=tuple(payload.get("evidence") or ()),
            iterations=int(payload.get("iterations") or 0),
            duration_ms=payload.get("duration_ms"),
            success=bool(payload.get("success") is True),
            error=(str(payload.get("error")) if payload.get("error") else None),
        )
    return results


def resume_deep_research(
    *,
    workflow: DeepResearchWorkflow,
    data_dir: str,
    session_id: str,
    query: str,
    max_attempts: int = 2,
) -> DeepResearchOutcome:
    session_dir = Path(data_dir) / session_id
    plan_path = session_dir / "research" / "plan.json"
    workers_dir = session_dir / "research" / "workers"

    if not plan_path.exists():
        raise FileNotFoundError(f"Missing plan: {plan_path}")

    plan = _load_json(plan_path)
    tasks = workflow._to_worker_tasks(query, plan)  # noqa: SLF001 (internal, by design for resume)

    existing = _load_existing_worker_results(workers_dir)
    if existing:
        normalized = workflow._apply_worker_invariants(list(existing.values()))  # noqa: SLF001
        existing = {r.task_id: r for r in normalized}

    remaining = {t.id for t in tasks if not (existing.get(t.id) and existing[t.id].success)}
    attempts = 0
    while remaining and attempts < max(1, int(max_attempts)):
        attempts += 1
        to_run = [t for t in tasks if t.id in remaining]
        if not to_run:
            break

        rerun = workflow.parallel_runner.spawn_parallel(
            to_run,
            max_workers=workflow.config.max_workers,
            timeout=workflow.config.worker_timeout_s,
            allow_writes=False,
        )
        rerun = workflow._apply_worker_invariants(rerun)  # noqa: SLF001
        for r in rerun:
            existing[r.task_id] = r
        remaining = {t.id for t in tasks if not (existing.get(t.id) and existing[t.id].success)}

    results = [existing.get(t.id) or WorkerResult(task_id=t.id, success=False, error="Missing worker result") for t in tasks]
    failures = [r for r in results if not r.success]
    if failures and not workflow.config.best_effort:
        raise RuntimeError(
            "Deep research resume failed because one or more workers are still failing.\n\n"
            f"Diagnostics:\n{workflow._format_worker_diagnostics(results)}"  # noqa: SLF001
        )

    citations = workflow._collect_citations_from_traces(results)  # noqa: SLF001
    findings = [
        {
            "task_id": r.task_id,
            "success": r.success,
            "output": r.output,
            "error": r.error,
            "citations": list(r.citations),
            "web_search_calls": int(r.web_search_calls or 0),
        }
        for r in results
    ]
    report, report_json = workflow._synthesize_and_render(  # noqa: SLF001
        query,
        findings,
        citations,
        report_type=detect_report_type(query),
    )

    return DeepResearchOutcome(
        query=query,
        plan=plan,
        tasks=tasks,
        results=results,
        citations=citations,
        report_markdown=report,
        report_json=report_json,
    )
