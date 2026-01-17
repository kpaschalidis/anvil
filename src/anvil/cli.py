import sys
import argparse
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from anvil.config import AgentConfig, resolve_model_alias
from anvil.modes.registry import get_mode, list_modes
from anvil.runtime.repl import AnvilREPL
from anvil.runtime.runtime import AnvilRuntime


def main():
    load_dotenv()

    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        raise SystemExit(_main_fetch(sys.argv[2:]))

    parser = argparse.ArgumentParser(description="Anvil - AI Coding Agent with Tools")
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model to use (supports aliases: sonnet, opus, haiku, flash, deepseek)",
    )
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't actually edit files"
    )
    parser.add_argument(
        "--no-auto-commit", action="store_true", help="Don't auto-commit"
    )
    parser.add_argument(
        "--no-tools", action="store_true", help="Disable structured tools"
    )
    parser.add_argument(
        "--no-lint", action="store_true", help="Disable auto-linting after edits"
    )
    parser.add_argument(
        "mode_or_file",
        nargs="?",
        default=None,
        help=f"Mode to run (available: {', '.join(list_modes())}); if not a mode, treated as a file",
    )
    parser.add_argument("files", nargs="*", help="Files to add to context")
    parser.add_argument("--message", "-m", help="Initial message")

    args = parser.parse_args()

    model = resolve_model_alias(args.model)

    config = AgentConfig(
        model=model,
        stream=not args.no_stream,
        dry_run=args.dry_run,
        auto_commit=not args.no_auto_commit,
        use_tools=not args.no_tools,
        auto_lint=not args.no_lint,
    )

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root_path = result.stdout.strip()
    except subprocess.CalledProcessError:
        print("❌ Error: Not in a git repository")
        sys.exit(1)

    mode_name = args.mode_or_file
    files = list(args.files)
    if mode_name is None:
        mode_name = "coding"
    elif mode_name not in list_modes():
        files = [mode_name] + files
        mode_name = "coding"

    try:
        mode_config = get_mode(mode_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    runtime = AnvilRuntime(root_path, config, mode=mode_config)

    for filepath in files:
        runtime.add_file_to_context(filepath)

    repl = AnvilREPL(runtime)
    repl.run(initial_message=args.message)


def _main_fetch(argv: list[str]) -> int:
    import logging

    from common.events import DocumentEvent, ErrorEvent, ProgressEvent
    from scout.config import ScoutConfig, ConfigError
    from scout.services.fetch import FetchConfig, FetchService

    parser = argparse.ArgumentParser(prog="anvil fetch", description="Fetch raw documents (Scout fetch-only)")
    parser.add_argument("topic")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Source name (repeatable), e.g. --source hackernews --source reddit",
    )
    parser.add_argument("--profile", default="quick", help="Scout profile (quick/standard/deep)")
    parser.add_argument("--max-documents", type=int, default=100)
    parser.add_argument("--data-dir", default="data/sessions")
    parser.add_argument("--deep-comments", default="auto", choices=["auto", "always", "never"])
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    source_names: list[str] = []
    for raw in args.source or []:
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                source_names.append(part)
    try:
        scout_config = ScoutConfig.from_profile(args.profile, sources=source_names)
        scout_config.validate(sources=source_names)
    except ConfigError as e:
        print(f"Error: {e}")
        return 1

    def on_event(event) -> None:
        if isinstance(event, ProgressEvent):
            if event.stage == "fetch":
                if event.total:
                    print(f"[{event.current}/{event.total}] {event.message}")
                else:
                    print(f"[{event.current}] {event.message}")
            return
        if isinstance(event, DocumentEvent):
            return
        if isinstance(event, ErrorEvent):
            print(f"Error: {event.message}", file=sys.stderr)

    service = FetchService(
        FetchConfig(
            topic=args.topic,
            sources=source_names,
            data_dir=args.data_dir,
            max_documents=args.max_documents,
            deep_comments=args.deep_comments,
        ),
        on_event=on_event,
    )
    result = service.run(scout_config=scout_config)

    print(f"Session: {result.session_id}")
    print(f"Documents: {result.documents_fetched}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.errors:
        print(f"Errors: {len(result.errors)} (see stderr)")
    return 0


if __name__ == "__main__":
    main()
