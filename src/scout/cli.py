import argparse
import logging
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()
load_dotenv("src/.env")

from scout.config import ScoutConfig, ConfigError
from scout.session import SessionManager, load_or_create_session, SessionError
from scout.agent import IngestionAgent
from scout.sources.registry import load_source_classes
from scout.storage import Storage
from scout.progress import ProgressInfo

def available_sources() -> set[str]:
    return set(load_source_classes().keys())


def build_sources(config: ScoutConfig, names: list[str]):
    classes = load_source_classes()
    sources = []
    for name in names:
        cls = classes.get(name)
        if not cls:
            continue
        if name == "hackernews":
            sources.append(cls(config.hackernews))
        elif name == "reddit":
            if config.reddit is None:
                continue
            sources.append(cls(config.reddit))
        elif name == "producthunt":
            sources.append(cls(config.producthunt))
        elif name == "github_issues":
            sources.append(cls(config.github_issues))
        else:
            try:
                sources.append(cls())
            except Exception:
                continue
    return sources


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(verbose: bool = False, quiet: bool = False, log_format: str = "text") -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_format == "json":
        handlers[0].setFormatter(JsonFormatter())
        logging.basicConfig(level=level, handlers=handlers)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("praw").setLevel(logging.WARNING)
    logging.getLogger("prawcore").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)


def cmd_run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, args.quiet, args.log_format)
    logger = logging.getLogger(__name__)

    source_names = args.source.split(",") if args.source else ["hackernews"]
    source_names = [s.strip() for s in source_names]

    avail = available_sources()
    for s in source_names:
        if s not in avail:
            print(
                f"Error: Unknown source '{s}'. Available: {', '.join(sorted(avail))}"
            )
            return 1

    try:
        config = ScoutConfig.from_profile(args.profile, sources=source_names)
        
        if args.max_iterations:
            config.max_iterations = args.max_iterations
        if args.max_documents:
            config.max_documents = args.max_documents
        if args.max_cost:
            config.max_cost_usd = args.max_cost
        if args.workers:
            config.parallel_workers = args.workers
        elif "producthunt" in source_names:
            # Product Hunt scraping uses Playwright; keep concurrency low by default.
            config.parallel_workers = 1
        if args.deep_comments:
            config.deep_comments = args.deep_comments
        if args.extraction_model:
            config.llm.extraction_model = args.extraction_model
        
        if args.min_content_length is not None or args.min_score is not None:
            from scout.filters import FilterConfig
            config.filter = FilterConfig(
                min_content_length=args.min_content_length if args.min_content_length is not None else config.filter.min_content_length,
                min_score=args.min_score if args.min_score is not None else config.filter.min_score,
                skip_deleted_authors=config.filter.skip_deleted_authors,
            )
        
        config.validate(sources=source_names)

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Error: {e}")
        if "reddit" in source_names:
            print("Make sure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set.")
        return 1

    try:
        session = load_or_create_session(
            session_id=args.resume,
            topic=args.topic,
            max_iterations=config.max_iterations,
            data_dir=config.data_dir,
        )
    except SessionError as e:
        logger.error(f"Session error: {e}")
        print(f"Error: {e}")
        return 1

    if args.resume:
        print(f"Resuming session {session.session_id}")
        print(f"Topic: {session.topic}")
        print(f"Status: {session.status}")
        print(f"Documents: {session.stats.docs_collected}")
        print(f"Remaining tasks: {len(session.task_queue)}")
    else:
        print(f"Starting new session: {session.session_id}")
        print(f"Topic: {session.topic}")
        print(f"Sources: {', '.join(source_names)}")

    if args.extraction_prompt:
        session.extraction_prompt_version = args.extraction_prompt
    config.llm.extraction_prompt_version = session.extraction_prompt_version
    
    if config.deep_comments == "always":
        print("⚠️  Warning: --deep-comments always is SLOW (fetches all comment trees)")
        print("   Consider using 'auto' (default) for faster runs")

    sources = build_sources(config, source_names)

    if not sources:
        print("Error: No sources configured.")
        return 1

    def on_progress(info: ProgressInfo) -> None:
        pct = (info.iteration / max(1, info.max_iterations)) * 100
        cost_str = f" cost=${info.total_cost_usd:.4f}" if info.total_cost_usd else ""
        
        if args.verbose:
            if info.iteration % 5 == 0:
                logger.info(
                    f"Progress: [{pct:3.0f}%] it={info.iteration}/{info.max_iterations} "
                    f"docs={info.docs_collected}/{info.max_documents} "
                    f"snips={info.snippets_extracted} tasks={info.tasks_remaining} "
                    f"nov={info.avg_novelty:.2f}{cost_str}"
                )
            return
        
        if args.quiet:
            line = (
                f"\r[{pct:3.0f}%] it={info.iteration}/{info.max_iterations} "
                f"docs={info.docs_collected}/{info.max_documents} "
                f"snips={info.snippets_extracted} tasks={info.tasks_remaining} "
                f"nov={info.avg_novelty:.2f}{cost_str}"
            )
            print(line, end="", flush=True)
        else:
            if info.iteration % 5 == 0 or info.iteration == 1:
                line = (
                    f"[{pct:3.0f}%] it={info.iteration}/{info.max_iterations} "
                    f"docs={info.docs_collected}/{info.max_documents} "
                    f"snips={info.snippets_extracted} tasks={info.tasks_remaining} "
                    f"nov={info.avg_novelty:.2f}{cost_str}"
                )
                print(line)

    agent = IngestionAgent(session, sources, config, on_progress=on_progress)

    try:
        agent.run()
        if args.quiet:
            print()
        print("\n=== Session Complete ===")
        print(f"Session ID: {session.session_id}")
        print(f"Documents: {session.stats.docs_collected}")
        print(f"Snippets: {session.stats.snippets_extracted}")
        print(f"Iterations: {session.stats.iterations}")
        if session.stats.total_cost_usd:
            print(f"Cost: ${session.stats.total_cost_usd:.4f}")
            print(f"Tokens: {session.stats.total_tokens}")
        return 0

    except KeyboardInterrupt:
        return 0

    except Exception as e:
        logger.exception("Agent failed")
        print(f"Error: {e}")
        return 1


def cmd_dump(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, args.quiet, args.log_format)
    logger = logging.getLogger(__name__)
    out_to_stdout = args.output == "-"

    source_names = args.source.split(",") if args.source else ["producthunt"]
    source_names = [s.strip() for s in source_names if s.strip()]

    avail = available_sources()
    for s in source_names:
        if s not in avail:
            print(
                f"Error: Unknown source '{s}'. Available: {', '.join(sorted(avail))}"
            )
            return 1

    try:
        config = ScoutConfig.from_profile(args.profile, sources=source_names)
        if args.max_iterations:
            config.max_iterations = args.max_iterations
        if args.max_documents:
            config.max_documents = args.max_documents
        if args.workers:
            config.parallel_workers = args.workers
        elif "producthunt" in source_names:
            # Product Hunt scraping uses Playwright; keep concurrency low by default.
            config.parallel_workers = 1
        if args.deep_comments:
            config.deep_comments = args.deep_comments
        if args.min_content_length is not None or args.min_score is not None:
            from scout.filters import FilterConfig

            config.filter = FilterConfig(
                min_content_length=args.min_content_length
                if args.min_content_length is not None
                else config.filter.min_content_length,
                min_score=args.min_score if args.min_score is not None else config.filter.min_score,
                skip_deleted_authors=config.filter.skip_deleted_authors,
            )

        config.validate(sources=source_names)

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Error: {e}")
        if "reddit" in source_names:
            print("Make sure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set.")
        return 1

    try:
        session = load_or_create_session(
            session_id=args.resume,
            topic=args.topic,
            max_iterations=config.max_iterations,
            data_dir=config.data_dir,
        )
    except SessionError as e:
        logger.error(f"Session error: {e}")
        print(f"Error: {e}")
        return 1

    if args.resume:
        print(f"Resuming session {session.session_id}", file=sys.stderr)
        print(f"Topic: {session.topic}", file=sys.stderr)
        print(f"Status: {session.status}", file=sys.stderr)
        print(f"Documents: {session.stats.docs_collected}", file=sys.stderr)
        print(f"Remaining tasks: {len(session.task_queue)}", file=sys.stderr)
    else:
        print(f"Starting new session: {session.session_id}", file=sys.stderr)
        print(f"Topic: {session.topic}", file=sys.stderr)
        print(f"Sources: {', '.join(source_names)}", file=sys.stderr)

    sources = build_sources(config, source_names)
    if not sources:
        print("Error: No sources configured.")
        return 1

    agent = IngestionAgent(session, sources, config, llm_enabled=False)
    try:
        agent.run()
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.exception("Dump run failed")
        print(f"Error: {e}")
        return 1

    session_dir = Path(config.data_dir) / session.session_id
    raw_path = session_dir / "raw.jsonl"

    if not raw_path.exists():
        print(f"No raw output found at: {raw_path}")
        return 1

    if out_to_stdout:
        with open(raw_path, "r", encoding="utf-8") as f:
            sys.stdout.write(f.read())
        return 0

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Wrote raw output: {out_path}", file=sys.stderr)
        return 0

    print(f"Raw documents: {raw_path}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)
    sessions = manager.list_sessions()

    if not sessions:
        print("No sessions found.")
        return 0

    print(f"{'ID':<12} {'Topic':<40} {'Status':<12} {'Docs':<8} {'Updated'}")
    print("-" * 100)

    for s in sessions:
        stats = s.get("stats", {})
        docs = stats.get("docs_collected", 0)
        topic = s.get("topic", "")[:38]
        updated = s.get("updated_at", "")[:19]
        print(
            f"{s.get('session_id', ''):<12} {topic:<40} {s.get('status', ''):<12} {docs:<8} {updated}"
        )

    return 0


def cmd_export(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)
    logger = logging.getLogger(__name__)

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    storage = Storage(args.session_id, data_dir)

    output_dir = Path(args.output) if args.output else Path(data_dir) / args.session_id

    if args.format == "jsonl":
        files = storage.export_jsonl(output_dir)
        print(f"Exported to:")
        for name, path in files.items():
            if path.exists():
                print(f"  {name}: {path}")
    elif args.format == "json":
        docs = list(storage.get_all_documents())
        snippets = list(storage.get_all_snippets())

        output_file = output_dir / "export.json"
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(
                {
                    "session_id": args.session_id,
                    "documents": [d.model_dump(mode="json") for d in docs],
                    "snippets": [s.model_dump(mode="json") for s in snippets],
                },
                f,
                indent=2,
                default=str,
            )

        print(f"Exported to: {output_file}")
        print(f"  Documents: {len(docs)}")
        print(f"  Snippets: {len(snippets)}")
    elif args.format == "csv":
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "snippets.csv"
        storage.export_csv(output_file)
        print(f"Exported to: {output_file}")
        print(f"  Snippets: {storage.get_snippet_count()}")
    elif args.format == "markdown":
        output_dir.mkdir(parents=True, exist_ok=True)
        manager = SessionManager(data_dir)
        session = manager.load_session(args.session_id)
        if not session:
            print(f"Session {args.session_id} not found.")
            return 1
        output_file = output_dir / "summary.md"
        storage.export_markdown_summary(output_file, session=session)
        print(f"Exported to: {output_file}")
    else:
        print(f"Unknown format: {args.format}")
        return 1

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)
    session = manager.load_session(args.session_id)

    if not session:
        print(f"Session {args.session_id} not found.")
        return 1

    storage = Storage(args.session_id, data_dir)

    print(f"Session: {session.session_id}")
    print(f"Topic: {session.topic}")
    print(f"Status: {session.status}")
    print(f"Complexity: {session.complexity}")
    print(f"Created: {session.created_at}")
    print(f"Updated: {session.updated_at}")
    print()
    print("Stats:")
    print(f"  Documents: {storage.get_document_count()}")
    print(f"  Snippets: {storage.get_snippet_count()}")
    print(f"  Iterations: {session.stats.iterations}")
    print(f"  Tasks remaining: {len(session.task_queue)}")
    print(f"  Avg novelty: {session.stats.avg_novelty:.2f}")
    if session.stats.total_cost_usd:
        print(f"  Cost: ${session.stats.total_cost_usd:.4f}")
        print(f"  Tokens: {session.stats.total_tokens}")
        print(f"  LLM calls: {session.stats.llm_calls}")
        print(f"    Extraction: {session.stats.extraction_calls}")
        print(f"    Complexity: {session.stats.complexity_calls}")
    print()
    print("Entities discovered:")
    entities = storage.get_all_entities()
    for entity in entities[:20]:
        print(f"  - {entity}")
    if len(entities) > 20:
        print(f"  ... and {len(entities) - 20} more")

    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)
    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    try:
        manager.tag_session(args.session_id, tags)
    except SessionError as e:
        print(f"Error: {e}")
        return 1
    print(f"Tagged session {args.session_id}: {', '.join(tags) if tags else '(none)'}")
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)
    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)
    try:
        new_session = manager.clone_session(args.session_id, topic=args.topic)
    except SessionError as e:
        print(f"Error: {e}")
        return 1
    print(f"Cloned session {args.session_id} -> {new_session.session_id}")
    print(f"Topic: {new_session.topic}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)
    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)
    try:
        moved = manager.archive_old_sessions(days=args.days)
    except SessionError as e:
        print(f"Error: {e}")
        return 1
    print(f"Archived {moved} sessions older than {args.days} days")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, getattr(args, "quiet", False), args.log_format)
    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    session_dir = Path(data_dir) / args.session_id
    filename = {
        "events": "events.jsonl",
        "snippets": "snippets.jsonl",
        "documents": "raw.jsonl",
    }.get(args.stream, "events.jsonl")
    path = session_dir / filename
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        if not args.from_start:
            f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(args.interval)
                    continue
                print(line.rstrip())
        except KeyboardInterrupt:
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scout",
        description="Scout - Product Discovery Research Agent",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Minimal logging (warnings/errors only, clean progress bar)"
    )
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="Log format (default: text)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    run_parser = subparsers.add_parser("run", help="Run research on a topic")
    run_parser.add_argument("topic", nargs="?", help="Topic to research")
    run_parser.add_argument(
        "--resume", "-r", metavar="SESSION_ID", help="Resume a paused session"
    )
    run_parser.add_argument(
        "--source",
        "-s",
        default="hackernews",
        help="Data sources (comma-separated): hackernews, reddit, producthunt, github_issues (default: hackernews)",
    )
    run_parser.add_argument(
        "--profile",
        "-p",
        choices=["quick", "standard", "deep"],
        default="standard",
        help="Research profile (default: standard)",
    )
    run_parser.add_argument(
        "--max-iterations", "-i", type=int, help="Maximum iterations"
    )
    run_parser.add_argument(
        "--max-documents", "-d", type=int, help="Maximum documents to collect"
    )
    run_parser.add_argument(
        "--max-cost",
        type=float,
        help="Maximum estimated LLM cost in USD (stop when reached)",
    )
    run_parser.add_argument(
        "--extraction-prompt",
        choices=["v1", "v2"],
        help="Extraction prompt version to use (default: session setting)",
    )
    run_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        metavar="N",
        help="Number of parallel workers (default: 5)",
    )
    run_parser.add_argument(
        "--deep-comments",
        choices=["auto", "always", "never"],
        metavar="MODE",
        help="Comment depth strategy: auto (default), always, never",
    )
    run_parser.add_argument(
        "--extraction-model",
        metavar="MODEL",
        help="LLM model for extraction (e.g., gpt-4o, gpt-4o-mini, claude-sonnet-4)",
    )
    run_parser.add_argument(
        "--min-content-length",
        type=int,
        metavar="N",
        help="Skip documents shorter than N characters (filter)",
    )
    run_parser.add_argument(
        "--min-score",
        type=int,
        metavar="N",
        help="Skip documents with score below N (filter)",
    )
    run_parser.set_defaults(func=cmd_run)

    dump_parser = subparsers.add_parser(
        "dump", help="Collect and output raw documents (no LLM)"
    )
    dump_parser.add_argument("topic", nargs="?", help="Topic to search for")
    dump_parser.add_argument(
        "--resume", "-r", metavar="SESSION_ID", help="Resume a paused session"
    )
    dump_parser.add_argument(
        "--source",
        "-s",
        default="producthunt",
        help="Data sources (comma-separated): hackernews, reddit, producthunt, github_issues (default: producthunt)",
    )
    dump_parser.add_argument(
        "--profile",
        "-p",
        choices=["quick", "standard", "deep"],
        default="quick",
        help="Collection profile (default: quick)",
    )
    dump_parser.add_argument(
        "--max-iterations", "-i", type=int, help="Maximum iterations"
    )
    dump_parser.add_argument(
        "--max-documents", "-d", type=int, help="Maximum documents to collect"
    )
    dump_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        metavar="N",
        help="Number of parallel workers (default: 5)",
    )
    dump_parser.add_argument(
        "--deep-comments",
        choices=["auto", "always", "never"],
        metavar="MODE",
        help="Comment depth strategy: auto, always, never",
    )
    dump_parser.add_argument(
        "--min-content-length",
        type=int,
        metavar="N",
        help="Skip documents shorter than N characters (filter)",
    )
    dump_parser.add_argument(
        "--min-score",
        type=int,
        metavar="N",
        help="Skip documents with score below N (filter)",
    )
    dump_parser.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        help="Write raw JSONL to PATH (use '-' for stdout; omit to only print the session raw.jsonl path)",
    )
    dump_parser.set_defaults(func=cmd_dump)

    list_parser = subparsers.add_parser("list", help="List all sessions")
    list_parser.set_defaults(func=cmd_list)

    export_parser = subparsers.add_parser("export", help="Export session data")
    export_parser.add_argument("session_id", help="Session ID to export")
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["jsonl", "json", "csv", "markdown"],
        default="jsonl",
        help="Export format",
    )
    export_parser.add_argument("--output", "-o", help="Output directory")
    export_parser.set_defaults(func=cmd_export)

    stats_parser = subparsers.add_parser("stats", help="Show session statistics")
    stats_parser.add_argument("session_id", help="Session ID")
    stats_parser.set_defaults(func=cmd_stats)

    tag_parser = subparsers.add_parser("tag", help="Tag a session")
    tag_parser.add_argument("session_id", help="Session ID")
    tag_parser.add_argument("--tags", required=True, help="Comma-separated tags")
    tag_parser.set_defaults(func=cmd_tag)

    clone_parser = subparsers.add_parser("clone", help="Clone a session")
    clone_parser.add_argument("session_id", help="Session ID")
    clone_parser.add_argument("--topic", help="Override topic for cloned session")
    clone_parser.set_defaults(func=cmd_clone)

    archive_parser = subparsers.add_parser("archive", help="Archive old sessions")
    archive_parser.add_argument(
        "--days", type=int, default=30, help="Archive sessions older than N days"
    )
    archive_parser.set_defaults(func=cmd_archive)

    watch_parser = subparsers.add_parser("watch", help="Tail session outputs")
    watch_parser.add_argument("session_id", help="Session ID")
    watch_parser.add_argument(
        "--stream",
        choices=["events", "snippets", "documents"],
        default="events",
        help="Which stream to tail (default: events)",
    )
    watch_parser.add_argument(
        "--from-start",
        action="store_true",
        help="Print from start instead of tailing",
    )
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds (default: 0.5)",
    )
    watch_parser.set_defaults(func=cmd_watch)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
