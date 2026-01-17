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
        for r in outcome.results:
            write_json(
                workers_dir / f"{r.task_id}.json",
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "error": r.error,
                    "web_search_calls": r.web_search_calls,
                    "citations": list(r.citations),
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
        "workers_dir": workers_dir,
        "report_path": report_path,
    }
