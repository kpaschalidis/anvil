import argparse
import logging
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()
load_dotenv("src/.env")

from scout.config import ScoutConfig, ConfigError
from scout.session import SessionManager, load_or_create_session, SessionError
from scout.agent import IngestionAgent
from scout.sources.reddit import RedditSource
from scout.sources.hackernews import HackerNewsSource
from scout.storage import Storage

AVAILABLE_SOURCES = ["hackernews", "reddit"]


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


def setup_logging(verbose: bool = False, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
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


def cmd_run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, args.log_format)
    logger = logging.getLogger(__name__)

    source_names = args.source.split(",") if args.source else ["hackernews"]
    source_names = [s.strip() for s in source_names]

    for s in source_names:
        if s not in AVAILABLE_SOURCES:
            print(
                f"Error: Unknown source '{s}'. Available: {', '.join(AVAILABLE_SOURCES)}"
            )
            return 1

    try:
        config = ScoutConfig.from_env(sources=source_names)
        config.validate(sources=source_names)

        if args.max_iterations:
            config.max_iterations = args.max_iterations
        if args.max_documents:
            config.max_documents = args.max_documents
        if args.max_cost:
            config.max_cost_usd = args.max_cost

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

    sources = []
    if "hackernews" in source_names:
        sources.append(HackerNewsSource(config.hackernews))
    if "reddit" in source_names and config.reddit:
        sources.append(RedditSource(config.reddit))

    if not sources:
        print("Error: No sources configured.")
        return 1

    agent = IngestionAgent(session, sources, config)

    try:
        agent.run()
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


def cmd_list(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, args.log_format)

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
    setup_logging(args.verbose, args.log_format)
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
    else:
        print(f"Unknown format: {args.format}")
        return 1

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    setup_logging(args.verbose, args.log_format)

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


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="scout",
        description="Scout - Product Discovery Research Agent",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
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
        help="Data sources (comma-separated): hackernews, reddit (default: hackernews)",
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
    run_parser.set_defaults(func=cmd_run)

    list_parser = subparsers.add_parser("list", help="List all sessions")
    list_parser.set_defaults(func=cmd_list)

    export_parser = subparsers.add_parser("export", help="Export session data")
    export_parser.add_argument("session_id", help="Session ID to export")
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["jsonl", "json"],
        default="jsonl",
        help="Export format",
    )
    export_parser.add_argument("--output", "-o", help="Output directory")
    export_parser.set_defaults(func=cmd_export)

    stats_parser = subparsers.add_parser("stats", help="Show session statistics")
    stats_parser.add_argument("session_id", help="Session ID")
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
