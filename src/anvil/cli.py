from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from anvil.config import AgentConfig, resolve_model_alias
from anvil.modes.registry import get_mode, list_modes
from anvil.runtime.repl import AnvilREPL
from anvil.runtime.runtime import AnvilRuntime


def main() -> int:
    load_dotenv()
    return _main(sys.argv[1:])


def _utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git_root_or_exit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Not in a git repository", file=sys.stderr)
        raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anvil", description="Anvil - AI Agent")
    subparsers = parser.add_subparsers(dest="command", required=False)

    repl = subparsers.add_parser("repl", help="Start interactive agent REPL")
    repl.add_argument(
        "--model",
        default="gpt-4o",
        help="Model to use (supports aliases: sonnet, opus, haiku, flash, deepseek)",
    )
    repl.add_argument("--no-stream", action="store_true", help="Disable streaming")
    repl.add_argument("--dry-run", action="store_true", help="Don't actually edit files")
    repl.add_argument("--no-auto-commit", action="store_true", help="Don't auto-commit")
    repl.add_argument("--no-tools", action="store_true", help="Disable structured tools")
    repl.add_argument("--no-lint", action="store_true", help="Disable auto-linting after edits")
    repl.add_argument("--mode", default="coding", choices=list_modes())
    repl.add_argument("--message", "-m", help="Single prompt (non-interactive)")
    repl.add_argument("files", nargs="*", help="Files to add to context")

    code = subparsers.add_parser("code", help="Run a coding task (non-interactive)")
    code.add_argument("task")
    code.add_argument("files", nargs="*")
    code.add_argument("--model", default="gpt-4o")
    code.add_argument("--max-iterations", type=int, default=10)

    fetch = subparsers.add_parser("fetch", help="Fetch raw documents (Scout fetch-only)")
    fetch.add_argument("topic", nargs="?", help="Topic to search (required unless --resume)")
    fetch.add_argument(
        "--source",
        action="append",
        help="Source name (repeatable), e.g. --source hackernews --source reddit",
    )
    fetch.add_argument("--profile", default="quick", help="Scout profile (quick/standard/deep)")
    fetch.add_argument("--max-documents", type=int, default=100)
    fetch.add_argument("--max-task-pages", type=int, default=3)
    fetch.add_argument("--data-dir", default="data/sessions")
    fetch.add_argument("--deep-comments", default="auto", choices=["auto", "always", "never"])
    fetch.add_argument("--session-id", default=None, help="Explicit session id for a new run")
    fetch.add_argument("--resume", default=None, help="Resume an existing session id")
    fetch.add_argument("-v", "--verbose", action="store_true")

    research = subparsers.add_parser("research", help="Deep research (Tavily + orchestrator-workers)")
    research.add_argument("query", nargs="?", help="Research query (required unless --resume)")
    research.add_argument("--profile", default="quick", choices=["quick", "deep"])
    research.add_argument("--model", default="gpt-4o")
    research.add_argument("--max-workers", type=int, default=None, help="Parallel worker concurrency")
    research.add_argument("--worker-iterations", type=int, default=None)
    research.add_argument("--worker-timeout", type=float, default=None)
    research.add_argument("--max-rounds", type=int, default=None, help="Max research rounds (default depends on profile)")
    research.add_argument("--max-tasks-total", type=int, default=None, help="Hard cap on total tasks across all rounds")
    research.add_argument("--max-tasks-per-round", type=int, default=None, help="Max planned tasks per round")
    research.add_argument("--verify-tasks-round3", type=int, default=None, help="Verification tasks in final round (deep)")
    research.add_argument("--page-size", type=int, default=None, help="Tavily page_size (1-20)")
    research.add_argument("--max-pages", type=int, default=None, help="Encourage pagination up to N pages")
    research.add_argument("--target-web-search-calls", type=int, default=None, help="Target web_search calls per worker (guidance only)")
    research.add_argument("--min-web-search-calls", type=int, default=None, help="(Deprecated) Alias for --target-web-search-calls")
    research.add_argument("--max-web-search-calls", type=int, default=None, help="Max web_search calls per worker")
    research.add_argument("--max-web-extract-calls", type=int, default=None, help="Max web_extract calls per worker (deep read)")
    research.add_argument("--extract-max-chars", type=int, default=None, help="Max chars returned per web_extract call")
    research.add_argument("--min-domains", type=int, default=None, help="Min unique domains across all citations")
    research.add_argument("--min-citations", type=int, default=None)
    research.add_argument(
        "--curated-max-total",
        type=int,
        default=None,
        help="Curated source pack max size for synthesis (quick defaults to 30; 0 disables)",
    )
    research.add_argument(
        "--curated-max-per-domain",
        type=int,
        default=None,
        help="Curated source pack max URLs per domain (quick defaults to 2; 0 disables)",
    )
    research.add_argument(
        "--curated-min-per-task",
        type=int,
        default=None,
        help="Curated source pack minimum URLs per task when possible (quick defaults to 3)",
    )
    research.add_argument("--data-dir", default="data/sessions")
    research.add_argument("--session-id", default=None)
    research.add_argument("--resume", default=None, help="Resume an existing research session id")
    research.add_argument("--max-attempts", type=int, default=2, help="Retries for failed workers on resume")
    research.add_argument("--output", default=None, help="Write report markdown to this path")
    research.add_argument("--no-save-artifacts", action="store_true")
    research.add_argument(
        "--best-effort",
        action="store_true",
        help="Allow partial output (not recommended; strict is default)",
    )
    research.add_argument(
        "--coverage-warn",
        action="store_true",
        help="Do not fail if report coverage targets (citations/domains) are missed; warn instead",
    )
    research.add_argument(
        "--coverage-strict",
        action="store_true",
        help="Fail if report coverage targets (citations/domains) are missed after repair",
    )

    sessions = subparsers.add_parser("sessions", help="List/open session artifacts")
    sessions.add_argument("--data-dir", default="data/sessions")
    sessions_sub = sessions.add_subparsers(dest="sessions_cmd", required=False)

    sessions_list = sessions_sub.add_parser("list", help="List sessions")
    sessions_list.add_argument("--kind", default=None, choices=["research", "fetch"])
    sessions_list.add_argument("--limit", type=int, default=20)

    sessions_show = sessions_sub.add_parser("show", help="Show session metadata")
    sessions_show.add_argument("session_id")

    sessions_open = sessions_sub.add_parser("open", help="Open research report")
    sessions_open.add_argument("session_id")
    sessions_open.add_argument(
        "--artifact",
        default=None,
        choices=["report", "raw", "db", "state", "meta"],
        help="Which artifact to open (defaults to report if present, else raw.jsonl)",
    )

    sessions_dir = sessions_sub.add_parser("dir", help="Print session directory")
    sessions_dir.add_argument("session_id")

    sessions_paths = sessions_sub.add_parser("paths", help="Print common artifact paths for a session")
    sessions_paths.add_argument("session_id")

    gui = subparsers.add_parser("gui", help="Launch Gradio web interface")
    gui.add_argument("--port", type=int, default=7860)
    gui.add_argument("--share", action="store_true", help="Create public link")

    return parser


def _main(argv: list[str]) -> int:
    if not argv:
        return _cmd_repl(
            model="gpt-4o",
            mode="coding",
            files=[],
            message=None,
            no_stream=False,
            dry_run=False,
            no_auto_commit=False,
            no_tools=False,
            no_lint=False,
        )

    parser = _build_parser()
    args = parser.parse_args(argv)

    cmd = args.command or "repl"
    if cmd == "repl":
        return _cmd_repl(
            model=args.model,
            mode=args.mode,
            files=list(args.files),
            message=args.message,
            no_stream=bool(args.no_stream),
            dry_run=bool(args.dry_run),
            no_auto_commit=bool(args.no_auto_commit),
            no_tools=bool(args.no_tools),
            no_lint=bool(args.no_lint),
        )
    if cmd == "code":
        return _cmd_code(args)
    if cmd == "fetch":
        return _cmd_fetch(args)
    if cmd == "research":
        return _cmd_research(args)
    if cmd == "sessions":
        return _cmd_sessions(args)
    if cmd == "gui":
        return _cmd_gui(args)

    parser.print_help(sys.stderr)
    return 2


def _cmd_repl(
    *,
    model: str,
    mode: str,
    files: list[str],
    message: str | None,
    no_stream: bool,
    dry_run: bool,
    no_auto_commit: bool,
    no_tools: bool,
    no_lint: bool,
) -> int:
    config = AgentConfig(
        model=resolve_model_alias(model),
        stream=not no_stream,
        dry_run=bool(dry_run),
        auto_commit=not bool(no_auto_commit),
        use_tools=not bool(no_tools),
        auto_lint=not bool(no_lint),
    )
    root_path = _git_root_or_exit()
    runtime = AnvilRuntime(root_path, config, mode=get_mode(mode))
    for filepath in files:
        runtime.add_file_to_context(filepath)

    if message:
        print(runtime.run_prompt(message, files=[]))
        return 0

    repl = AnvilREPL(runtime)
    repl.run(initial_message=None)
    return 0


def _cmd_code(args) -> int:
    from anvil.services.coding import CodingConfig, CodingService

    root_path = _git_root_or_exit()
    service = CodingService(
        CodingConfig(
            root_path=root_path,
            model=resolve_model_alias(args.model),
            max_iterations=int(args.max_iterations),
            mode="coding",
        )
    )
    result = service.run(prompt=args.task, files=list(args.files))
    if result.final_response:
        print(result.final_response)
    return 0


def _cmd_fetch(args) -> int:
    from common.events import DocumentEvent, ErrorEvent, ProgressEvent
    from scout.config import ScoutConfig, ConfigError
    from scout.services.fetch import FetchConfig, FetchService
    from scout.session import SessionManager

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    data_dir = str(args.data_dir)
    resume_id = (args.resume or "").strip() or None
    session_id = (args.session_id or "").strip() or None
    topic = (args.topic or "").strip()

    if resume_id:
        session_id = resume_id
        session = SessionManager(data_dir).load_session(resume_id)
        if session is None:
            print(f"Error: Session {resume_id} not found", file=sys.stderr)
            return 1
        if not topic:
            topic = session.topic

    if not topic:
        print("Error: topic is required (or use `anvil fetch --resume <session_id>`)", file=sys.stderr)
        return 2

    source_names: list[str] = []
    for raw in args.source or []:
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                source_names.append(part)

    if resume_id and not source_names:
        session = SessionManager(data_dir).load_session(resume_id)
        if session:
            source_names = sorted({t.source for t in session.task_queue})

    if not source_names:
        print("Error: at least one `--source` is required", file=sys.stderr)
        return 2

    try:
        scout_config = ScoutConfig.from_profile(args.profile, sources=source_names)
        scout_config.validate(sources=source_names)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    def on_event(event) -> None:
        if isinstance(event, ProgressEvent) and event.stage == "fetch":
            if event.total:
                print(f"[fetch] [{event.current}/{event.total}] {event.message}")
            else:
                print(f"[fetch] [{event.current}] {event.message}")
        elif isinstance(event, ErrorEvent):
            print(f"Error: {event.message}", file=sys.stderr)
        elif isinstance(event, DocumentEvent):
            pass

    service = FetchService(
        FetchConfig(
            topic=topic,
            sources=source_names,
            data_dir=data_dir,
            max_documents=int(args.max_documents),
            max_task_pages=int(args.max_task_pages),
            deep_comments=args.deep_comments,
            session_id=session_id,
            resume=bool(resume_id),
            write_meta=True,
        ),
        on_event=on_event,
    )
    result = service.run(scout_config=scout_config)

    print(f"Session: {result.session_id}")
    print(f"Documents: {result.documents_fetched}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.errors:
        print(f"Errors: {len(result.errors)}", file=sys.stderr)
    return 0


def _cmd_research(args) -> int:
    import os

    query = (args.query or "").strip()
    resume_id = (args.resume or "").strip() or None
    if not query and not resume_id:
        print("Error: query is required (or use `anvil research --resume <session_id>`)", file=sys.stderr)
        return 2

    missing_key = not bool(os.environ.get("TAVILY_API_KEY"))
    try:
        import tavily  # type: ignore[import-not-found]  # noqa: F401

        missing_pkg = False
    except Exception:
        missing_pkg = True

    if missing_key or missing_pkg:
        if missing_pkg:
            print("Error: `tavily-python` is not installed. Run: `uv sync --extra search`.", file=sys.stderr)
        if missing_key:
            print("Error: `TAVILY_API_KEY` is not set (add it to `.env` or export it).", file=sys.stderr)
        return 2

    from anvil.sessions.meta import load_meta, write_meta
    from anvil.subagents.parallel import ParallelWorkerRunner
    from anvil.workflows.deep_research import (
        DeepResearchConfig,
        DeepResearchRunError,
        DeepResearchWorkflow,
        PlanningError,
    )
    from anvil.workflows.deep_research_resume import resume_deep_research
    from anvil.workflows.research_artifacts import make_research_session_dir, write_json, write_text
    from anvil.workflows.research_persist import persist_research_outcome
    from common.events import EventEmitter, ProgressEvent
    from common.ids import generate_id

    root_path = _git_root_or_exit()
    runtime = AnvilRuntime(
        root_path,
        AgentConfig(model=resolve_model_alias(args.model), stream=False, use_tools=True),
        mode=get_mode("coding"),
    )

    def _log(stage: str, msg: str) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"{now} [{stage}] {msg}", file=sys.stderr)

    def on_event(event) -> None:
        if isinstance(event, ProgressEvent):
            msg = event.message or event.stage
            _log(event.stage, msg)
            return
        from common.events import ResearchPlanEvent, WorkerCompletedEvent

        if isinstance(event, ResearchPlanEvent):
            _log("plan", f"Planned {len(event.tasks)} tasks")
            for t in event.tasks[:20]:
                tid = str(t.get("id") or "").strip()
                q = str(t.get("search_query") or "").strip()
                _log("plan", f"- {tid}: {q}")
            return
        if isinstance(event, WorkerCompletedEvent):
            dt = ""
            if event.duration_ms is not None:
                dt = f" {event.duration_ms}ms"
            status = "ok" if event.success else "fail"
            extra = (
                f" searches={event.web_search_calls} extracts={event.web_extract_calls} evidence={event.evidence}"
                f" citations={event.citations} domains={event.domains}{dt}"
            )
            if not event.success and event.error:
                extra += f" error={event.error}"
            _log("worker", f"{event.task_id} {status}{extra}")
            return

    profile = str(getattr(args, "profile", "quick") or "quick")

    def _p(v, default):
        return default if v is None else v

    if profile == "deep":
        defaults = {
            "max_workers": 6,
            "worker_iterations": 12,
            "worker_timeout": 300.0,
            "max_rounds": 3,
            "max_tasks_total": 12,
            "max_tasks_per_round": 6,
            "verify_tasks_round3": 2,
            "page_size": 10,
            "max_pages": 4,
            "target_web_search_calls": 4,
            "max_web_search_calls": 8,
            "max_web_extract_calls": 3,
            "extract_max_chars": 20000,
            "min_citations": 15,
            "min_domains": 6,
            "report_min_citations": 20,
            "report_min_domains": 6,
            "report_findings": 8,
            "coverage_mode": "error",
            "curated_sources_max_total": 0,
            "curated_sources_max_per_domain": 0,
            "curated_sources_min_per_task": 0,
            "enable_worker_continuation": True,
            "max_worker_continuations": 2,
            "enable_deep_read": True,
            "require_quote_per_claim": True,
            "multi_pass_synthesis": True,
        }
    else:
        defaults = {
            "max_workers": 3,
            "worker_iterations": 6,
            "worker_timeout": 120.0,
            "max_rounds": 1,
            "max_tasks_total": 5,
            "max_tasks_per_round": 5,
            "verify_tasks_round3": 0,
            "page_size": 6,
            "max_pages": 2,
            "target_web_search_calls": 2,
            "max_web_search_calls": 4,
            "max_web_extract_calls": 0,
            "extract_max_chars": 20000,
            "min_citations": 3,
            "min_domains": 3,
            "report_min_citations": 8,
            "report_min_domains": 3,
            "report_findings": 5,
            "coverage_mode": "warn",
            "curated_sources_max_total": 30,
            "curated_sources_max_per_domain": 2,
            "curated_sources_min_per_task": 3,
            "enable_worker_continuation": False,
            "max_worker_continuations": 0,
            "enable_deep_read": False,
            "require_quote_per_claim": False,
            "multi_pass_synthesis": False,
        }

    max_workers = int(_p(args.max_workers, defaults["max_workers"]))
    worker_iterations = int(_p(args.worker_iterations, defaults["worker_iterations"]))
    worker_timeout = float(_p(args.worker_timeout, defaults["worker_timeout"]))
    max_rounds = int(_p(args.max_rounds, defaults["max_rounds"]))
    max_tasks_total = int(_p(args.max_tasks_total, defaults["max_tasks_total"]))
    max_tasks_per_round = int(_p(args.max_tasks_per_round, defaults["max_tasks_per_round"]))
    verify_tasks_round3 = int(_p(args.verify_tasks_round3, defaults["verify_tasks_round3"]))
    page_size = int(_p(args.page_size, defaults["page_size"]))
    max_pages = int(_p(args.max_pages, defaults["max_pages"]))
    target_web_search_calls = int(
        _p(_p(args.target_web_search_calls, args.min_web_search_calls), defaults["target_web_search_calls"])
    )
    max_web_search_calls = int(_p(args.max_web_search_calls, defaults["max_web_search_calls"]))
    max_web_extract_calls = int(_p(args.max_web_extract_calls, defaults["max_web_extract_calls"]))
    extract_max_chars = int(_p(args.extract_max_chars, defaults["extract_max_chars"]))
    min_citations = int(_p(args.min_citations, defaults["min_citations"]))
    min_domains = int(_p(args.min_domains, defaults["min_domains"]))
    report_min_citations = int(defaults["report_min_citations"])
    report_min_domains = int(defaults["report_min_domains"])
    report_findings = int(defaults["report_findings"])
    coverage_mode = str(defaults["coverage_mode"])
    curated_sources_max_total = int(defaults["curated_sources_max_total"])
    curated_sources_max_per_domain = int(defaults["curated_sources_max_per_domain"])
    curated_sources_min_per_task = int(defaults["curated_sources_min_per_task"])
    if args.curated_max_total is not None:
        curated_sources_max_total = int(args.curated_max_total)
    if args.curated_max_per_domain is not None:
        curated_sources_max_per_domain = int(args.curated_max_per_domain)
    if args.curated_min_per_task is not None:
        curated_sources_min_per_task = int(args.curated_min_per_task)
    if curated_sources_max_total < 0 or curated_sources_max_per_domain < 0 or curated_sources_min_per_task < 0:
        print("Error: curated pack arguments must be >= 0", file=sys.stderr)
        return 2
    if bool(args.coverage_warn) and bool(args.coverage_strict):
        print("Error: choose only one of --coverage-warn or --coverage-strict", file=sys.stderr)
        return 2
    if bool(args.coverage_warn):
        coverage_mode = "warn"
    if bool(args.coverage_strict):
        coverage_mode = "error"
    enable_worker_continuation = bool(defaults["enable_worker_continuation"])
    max_worker_continuations = int(defaults["max_worker_continuations"])
    enable_deep_read = bool(defaults["enable_deep_read"])
    require_quote_per_claim = bool(defaults["require_quote_per_claim"])
    multi_pass_synthesis = bool(defaults["multi_pass_synthesis"])

    workflow = DeepResearchWorkflow(
        subagent_runner=runtime.subagent_runner,
        parallel_runner=ParallelWorkerRunner(runtime.subagent_runner),
        config=DeepResearchConfig(
            model=resolve_model_alias(args.model),
            max_workers=max_workers,
            worker_max_iterations=worker_iterations,
            worker_timeout_s=worker_timeout,
            max_rounds=max_rounds,
            max_tasks_total=max_tasks_total,
            max_tasks_per_round=max_tasks_per_round,
            verify_tasks_round3=verify_tasks_round3,
            worker_max_attempts=int(max(1, int(args.max_attempts))),
            page_size=page_size,
            max_pages=max_pages,
            target_web_search_calls=target_web_search_calls,
            max_web_search_calls=max_web_search_calls,
            enable_deep_read=enable_deep_read,
            max_web_extract_calls=max_web_extract_calls,
            extract_max_chars=extract_max_chars,
            require_quote_per_claim=require_quote_per_claim,
            multi_pass_synthesis=multi_pass_synthesis,
            min_total_domains=min_domains,
            enable_worker_continuation=enable_worker_continuation,
            max_worker_continuations=max_worker_continuations,
            min_total_citations=max(0, min_citations),
            strict_all=True,
            best_effort=bool(args.best_effort),
            report_min_unique_citations_target=max(0, report_min_citations),
            report_min_unique_domains_target=max(0, report_min_domains),
            report_findings_target=max(1, report_findings),
            coverage_mode=coverage_mode,
            curated_sources_max_total=max(0, curated_sources_max_total),
            curated_sources_max_per_domain=max(0, curated_sources_max_per_domain),
            curated_sources_min_per_task=max(0, curated_sources_min_per_task),
        ),
        emitter=EventEmitter(on_event),
    )

    session_id = (args.session_id or "").strip() or generate_id()
    if resume_id:
        session_id = resume_id
    session_dir = make_research_session_dir(data_dir=args.data_dir, session_id=session_id)
    meta_path = session_dir / "meta.json"

    existing_meta = load_meta(data_dir=args.data_dir, session_id=session_id) if resume_id else None
    if resume_id and not query:
        query = str((existing_meta or {}).get("query") or "").strip()
        if not query:
            print(
                f"Error: missing query; provide it explicitly or ensure `{meta_path}` contains `query`",
                file=sys.stderr,
            )
            return 2

    meta = dict(existing_meta or {})
    meta.update(
        {
            "kind": "research",
            "session_id": session_id,
            "query": query,
            "model": resolve_model_alias(args.model),
            "status": "running",
            "config": {
                "profile": profile,
                "max_workers": int(max_workers),
                "worker_iterations": int(worker_iterations),
                "worker_timeout": float(worker_timeout),
                "max_rounds": int(max_rounds),
                "max_tasks_total": int(max_tasks_total),
                "max_tasks_per_round": int(max_tasks_per_round),
                "verify_tasks_round3": int(verify_tasks_round3),
                "page_size": page_size,
                "max_pages": max_pages,
                "target_web_search_calls": target_web_search_calls,
                "max_web_search_calls": max_web_search_calls,
                "max_web_extract_calls": max_web_extract_calls,
                "extract_max_chars": extract_max_chars,
                "enable_deep_read": bool(enable_deep_read),
                "require_quote_per_claim": bool(require_quote_per_claim),
                "multi_pass_synthesis": bool(multi_pass_synthesis),
                "enable_worker_continuation": bool(enable_worker_continuation),
                "max_worker_continuations": int(max_worker_continuations),
                "min_citations": min_citations,
                "min_domains": min_domains,
                "best_effort": bool(args.best_effort),
                "resume": bool(resume_id),
                "worker_max_attempts": int(args.max_attempts),
                "report_min_citations": int(report_min_citations),
                "report_min_domains": int(report_min_domains),
                "report_findings": int(report_findings),
                "coverage_mode": str(coverage_mode),
                "curated_sources_max_total": int(curated_sources_max_total),
                "curated_sources_max_per_domain": int(curated_sources_max_per_domain),
                "curated_sources_min_per_task": int(curated_sources_min_per_task),
            },
        }
    )
    write_meta(data_dir=args.data_dir, session_id=session_id, meta=meta)

    started = time.perf_counter()
    try:
        if resume_id:
            outcome = resume_deep_research(
                workflow=workflow,
                data_dir=args.data_dir,
                session_id=session_id,
                query=query,
                max_attempts=int(args.max_attempts),
            )
        else:
            outcome = workflow.run(query)

        failures = [r for r in outcome.results if not r.success]
        print(
            f"[diagnostics] tasks={len(outcome.results)} failed={len(failures)} citations={len(outcome.citations)}",
            file=sys.stderr,
        )
        for r in outcome.results:
            print(
                (
                    f"[diagnostics] {r.task_id}: success={r.success}"
                    f" web_search_calls={r.web_search_calls}"
                    f" web_extract_calls={getattr(r, 'web_extract_calls', 0) or 0}"
                    f" evidence={len(getattr(r, 'evidence', ()) or ())}"
                    f" citations={len(r.citations)}"
                    f" error={r.error or ''}"
                ).rstrip(),
                file=sys.stderr,
            )

        report_urls: set[str] = set()
        report_payload = getattr(outcome, "report_json", None)
        if isinstance(report_payload, dict):
            fs = report_payload.get("findings")
            if isinstance(fs, list):
                for it in fs:
                    if not isinstance(it, dict):
                        continue
                    cites = it.get("citations")
                    if isinstance(cites, list):
                        for u in cites:
                            if isinstance(u, str) and u.startswith("http"):
                                report_urls.add(u)
                    ev = it.get("evidence")
                    if isinstance(ev, list):
                        for e in ev:
                            if isinstance(e, dict):
                                u = e.get("url")
                                if isinstance(u, str) and u.startswith("http"):
                                    report_urls.add(u)
        report_domains = {urlparse(u).netloc for u in report_urls}
        quality = "good" if (len(report_urls) >= report_min_citations and len(report_domains) >= report_min_domains) else "limited"
        reason = ""
        if quality != "good":
            parts = []
            if len(report_urls) < report_min_citations:
                parts.append("below citation target")
            if len(report_domains) < report_min_domains:
                parts.append("below domain target")
            reason = f" ({', '.join(parts)})" if parts else ""
        findings_count = report_findings
        if isinstance(report_payload, dict):
            fs = report_payload.get("findings")
            if isinstance(fs, list):
                findings_count = len(fs)
        print(
            f"[diagnostics] report: findings={findings_count} unique_citations={len(report_urls)} domains={len(report_domains)} quality={quality}{reason}",
            file=sys.stderr,
        )

        meta["status"] = "completed"
        meta["citations"] = len(outcome.citations)
        meta["workers"] = {"total": len(outcome.results), "failed": len(failures)}

        paths = persist_research_outcome(
            data_dir=args.data_dir,
            session_id=session_id,
            meta=meta,
            outcome=outcome,
            output_path=args.output,
            save_artifacts=not bool(args.no_save_artifacts),
        )
        write_meta(data_dir=args.data_dir, session_id=session_id, meta=meta)

        print(outcome.report_markdown)
        if not args.output:
            print(f"\nSaved: {paths['report_path']}", file=sys.stderr)
            print(f"Session: {session_id}", file=sys.stderr)
        elapsed_s = time.perf_counter() - started
        print(f"Elapsed: {elapsed_s:.1f}s", file=sys.stderr)
        return 0
    except Exception as e:
        meta["status"] = "failed"
        meta["updated_at"] = _utc_ts()
        meta["error"] = str(e)
        outcome = getattr(e, "outcome", None) if isinstance(e, DeepResearchRunError) else None
        if outcome is not None:
            failures = [r for r in outcome.results if not r.success]
            meta["citations"] = len(outcome.citations)
            meta["workers"] = {"total": len(outcome.results), "failed": len(failures)}
            if not args.no_save_artifacts:
                persist_research_outcome(
                    data_dir=args.data_dir,
                    session_id=session_id,
                    meta=meta,
                    outcome=outcome,
                    output_path=None,
                    save_artifacts=True,
                )
            else:
                write_json(meta_path, meta)
        else:
            write_json(meta_path, meta)
        if isinstance(e, PlanningError) and not args.no_save_artifacts:
            write_text(session_dir / "research" / "planner_raw.txt", (e.raw or "") + "\n")
            write_json(session_dir / "research" / "planner_error.json", {"error": str(e)})
        if not args.no_save_artifacts:
            write_text(session_dir / "research" / "error.txt", str(e) + "\n")
        print(f"Error: {e}", file=sys.stderr)
        print(f"Session: {session_id}", file=sys.stderr)
        print(f"Artifacts: {session_dir}", file=sys.stderr)
        elapsed_s = time.perf_counter() - started
        print(f"Elapsed: {elapsed_s:.1f}s", file=sys.stderr)
        return 1


def _cmd_sessions(args) -> int:
    from anvil.sessions.meta import list_sessions, load_meta

    data_dir = args.data_dir
    sub = args.sessions_cmd or "list"

    if sub == "list":
        rows = list_sessions(data_dir=data_dir, kind=args.kind)
        rows = rows[: max(0, int(args.limit))]
        if not rows:
            print("No sessions found.")
            return 0
        print(f"{'ID':<10} {'Kind':<10} {'Status':<22} {'Updated':<20} {'Summary'}")
        for m in rows:
            sid = str(m.get("session_id") or "")[:10]
            kind = str(m.get("kind") or "")
            status = str(m.get("status") or "")
            updated = str(m.get("updated_at") or m.get("created_at") or "")
            summary = str(m.get("query") or m.get("topic") or "")[:60]
            print(f"{sid:<10} {kind:<10} {status:<22} {updated:<20} {summary}")
        return 0

    if sub == "dir":
        print(Path(data_dir) / args.session_id)
        return 0

    if sub == "paths":
        base = Path(data_dir) / args.session_id
        print(base / "meta.json")
        print(base / "state.json")
        print(base / "raw.jsonl")
        print(base / "session.db")
        print(base / "research" / "report.md")
        print(base / "research" / "plan.json")
        print(base / "research" / "workers")
        return 0

    meta = load_meta(data_dir=data_dir, session_id=args.session_id) or {}
    if sub == "show":
        import json

        print(json.dumps(meta, indent=2, ensure_ascii=False))
        return 0

    if sub == "open":
        base = Path(data_dir) / args.session_id
        artifact = getattr(args, "artifact", None)
        if artifact == "meta":
            target = base / "meta.json"
        elif artifact == "state":
            target = base / "state.json"
        elif artifact == "raw":
            target = base / "raw.jsonl"
        elif artifact == "db":
            target = base / "session.db"
        else:
            report = base / "research" / "report.md"
            raw = base / "raw.jsonl"
            target = report if report.exists() else raw

        if not target.exists():
            print(f"Artifact not found: {target}", file=sys.stderr)
            return 1
        opener = None
        if sys.platform == "darwin":
            opener = ["open", str(target)]
        elif sys.platform.startswith("win"):
            opener = ["cmd", "/c", "start", str(target)]
        else:
            opener = ["xdg-open", str(target)]
        subprocess.run(opener, check=False)
        return 0

    return 2


def _cmd_gui(args) -> int:
    try:
        from anvil.gui import launch
    except ImportError:
        print("Gradio not installed. Run: `uv sync --extra gui`.", file=sys.stderr)
        return 1

    print(f"Launching Anvil GUI on port {args.port}...")
    launch(server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
