from __future__ import annotations

from pathlib import Path
from typing import Any

from anvil.workflows.research_artifacts import make_research_session_dir, write_json, write_text


def _worker_payload(r) -> dict[str, Any]:
    return {
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
    }


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
    synthesizer_raw_path = session_dir / "research" / "synthesizer_raw.txt"
    synthesizer_error_path = session_dir / "research" / "synthesizer_error.json"
    synthesis_input_path = session_dir / "research" / "synthesis_input.json"
    workers_dir = session_dir / "research" / "workers"
    rounds_dir = session_dir / "research" / "rounds"
    report_path = Path(output_path) if output_path else (session_dir / "research" / "report.md")
    report_json_path = session_dir / "research" / "report.json"

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

        synthesis_raw = getattr(outcome, "synthesis_raw", "") or ""
        synthesis_error = getattr(outcome, "synthesis_error", None)
        synthesis_stage = getattr(outcome, "synthesis_stage", None)
        if synthesis_raw:
            write_text(
                synthesizer_raw_path,
                synthesis_raw + ("\n" if not synthesis_raw.endswith("\n") else ""),
            )
        if synthesis_error or synthesis_stage:
            payload = {"error": str(synthesis_error) if synthesis_error else ""}
            if synthesis_stage:
                payload["stage"] = str(synthesis_stage)
            write_json(synthesizer_error_path, payload)

        synthesis_input = getattr(outcome, "synthesis_input", None)
        if isinstance(synthesis_input, dict):
            write_json(synthesis_input_path, synthesis_input)
        results_by_id = {r.task_id: r for r in outcome.results}
        for r in outcome.results:
            write_json(workers_dir / f"{r.task_id}.json", _worker_payload(r))

        rounds = getattr(outcome, "rounds", None)
        if isinstance(rounds, list) and rounds:
            for rd in rounds:
                if not isinstance(rd, dict):
                    continue
                idx = rd.get("round_index")
                try:
                    idx_i = int(idx)
                except Exception:
                    continue
                if idx_i <= 0:
                    continue
                stage = str(rd.get("stage") or "")
                round_dir = rounds_dir / f"round_{idx_i:02d}"
                meta_round = {
                    "round_index": idx_i,
                    "stage": stage,
                    "task_ids": rd.get("task_ids") or [],
                }
                write_json(round_dir / "meta.json", meta_round)
                plan = rd.get("plan")
                if isinstance(plan, dict) and plan.get("tasks"):
                    write_json(round_dir / "plan.json", plan)
                memo = rd.get("memo")
                if isinstance(memo, dict):
                    write_json(round_dir / "memo.json", memo)
                raw = rd.get("planner_raw")
                if isinstance(raw, str) and raw.strip():
                    write_text(round_dir / "planner_raw.txt", raw + ("\n" if not raw.endswith("\n") else ""))
                err = rd.get("planner_error")
                if err:
                    write_json(round_dir / "planner_error.json", {"error": str(err)})

                task_ids = rd.get("task_ids")
                if isinstance(task_ids, list):
                    wanted = {str(t) for t in task_ids if isinstance(t, str)}
                else:
                    wanted = set()
                if wanted:
                    for tid in sorted(wanted):
                        r = results_by_id.get(tid)
                        if r is None:
                            continue
                        write_json(round_dir / "workers" / f"{tid}.json", _worker_payload(r))

        report_json = getattr(outcome, "report_json", None)
        if isinstance(report_json, dict):
            write_json(report_json_path, report_json)

    if (getattr(outcome, "report_markdown", "") or "").strip():
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
        "synthesizer_raw_path": synthesizer_raw_path,
        "synthesizer_error_path": synthesizer_error_path,
        "synthesis_input_path": synthesis_input_path,
        "workers_dir": workers_dir,
        "rounds_dir": rounds_dir,
        "report_path": report_path,
        "report_json_path": report_json_path,
    }
