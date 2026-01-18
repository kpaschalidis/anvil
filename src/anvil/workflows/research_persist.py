from __future__ import annotations

from pathlib import Path
from typing import Any

from anvil.workflows.research_artifacts import make_research_session_dir, write_json, write_text


def persist_research_outcome(
    *,
    data_dir: str,
    session_id: str,
    meta: dict[str, Any],
    outcome,
    output_path: str | None = None,
    save_artifacts: bool = True,
) -> dict[str, Path]:
    session_dir = make_research_session_dir(data_dir=data_dir, session_id=session_id)
    meta_path = session_dir / "meta.json"
    plan_path = session_dir / "research" / "plan.json"
    planner_raw_path = session_dir / "research" / "planner_raw.txt"
    planner_error_path = session_dir / "research" / "planner_error.json"
    gap_plan_path = session_dir / "research" / "gap_plan.json"
    gap_planner_raw_path = session_dir / "research" / "gap_planner_raw.txt"
    gap_planner_error_path = session_dir / "research" / "gap_planner_error.json"
    verify_plan_path = session_dir / "research" / "verify_plan.json"
    verify_planner_raw_path = session_dir / "research" / "verify_planner_raw.txt"
    verify_planner_error_path = session_dir / "research" / "verify_planner_error.json"
    workers_dir = session_dir / "research" / "workers"
    report_path = Path(output_path) if output_path else (session_dir / "research" / "report.md")

    if save_artifacts and not output_path:
        write_json(plan_path, outcome.plan)
        planner_raw = getattr(outcome, "planner_raw", "") or ""
        planner_error = getattr(outcome, "planner_error", None)
        if planner_raw:
            write_text(planner_raw_path, planner_raw + ("\n" if not planner_raw.endswith("\n") else ""))
        if planner_error:
            write_json(planner_error_path, {"error": str(planner_error)})
        gap_plan = getattr(outcome, "gap_plan", None)
        gap_planner_raw = getattr(outcome, "gap_planner_raw", "") or ""
        gap_planner_error = getattr(outcome, "gap_planner_error", None)
        if isinstance(gap_plan, dict) and gap_plan.get("tasks"):
            write_json(gap_plan_path, gap_plan)
        if gap_planner_raw:
            write_text(
                gap_planner_raw_path,
                gap_planner_raw + ("\n" if not gap_planner_raw.endswith("\n") else ""),
            )
        if gap_planner_error:
            write_json(gap_planner_error_path, {"error": str(gap_planner_error)})
        verify_plan = getattr(outcome, "verify_plan", None)
        verify_planner_raw = getattr(outcome, "verify_planner_raw", "") or ""
        verify_planner_error = getattr(outcome, "verify_planner_error", None)
        if isinstance(verify_plan, dict) and verify_plan.get("tasks"):
            write_json(verify_plan_path, verify_plan)
        if verify_planner_raw:
            write_text(
                verify_planner_raw_path,
                verify_planner_raw + ("\n" if not verify_planner_raw.endswith("\n") else ""),
            )
        if verify_planner_error:
            write_json(verify_planner_error_path, {"error": str(verify_planner_error)})
        for r in outcome.results:
            write_json(
                workers_dir / f"{r.task_id}.json",
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "error": r.error,
                    "web_search_calls": r.web_search_calls,
                    "web_extract_calls": int(getattr(r, "web_extract_calls", 0) or 0),
                    "iterations": getattr(r, "iterations", 0),
                    "duration_ms": getattr(r, "duration_ms", None),
                    "citations": list(r.citations),
                    "sources": getattr(r, "sources", {}) or {},
                    "web_search_trace": list(getattr(r, "web_search_trace", ()) or ()),
                    "web_extract_trace": list(getattr(r, "web_extract_trace", ()) or ()),
                    "evidence": list(getattr(r, "evidence", ()) or ()),
                    "output": r.output,
                },
            )

    write_text(report_path, outcome.report_markdown + "\n")
    write_json(meta_path, meta)

    return {
        "session_dir": session_dir,
        "meta_path": meta_path,
        "plan_path": plan_path,
        "planner_raw_path": planner_raw_path,
        "planner_error_path": planner_error_path,
        "gap_plan_path": gap_plan_path,
        "gap_planner_raw_path": gap_planner_raw_path,
        "gap_planner_error_path": gap_planner_error_path,
        "verify_plan_path": verify_plan_path,
        "verify_planner_raw_path": verify_planner_raw_path,
        "verify_planner_error_path": verify_planner_error_path,
        "workers_dir": workers_dir,
        "report_path": report_path,
    }
