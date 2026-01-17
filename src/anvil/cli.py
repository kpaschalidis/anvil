import sys
import argparse
import subprocess

from dotenv import load_dotenv

from anvil.config import AgentConfig, resolve_model_alias
from anvil.modes.registry import get_mode, list_modes
from anvil.runtime.repl import AnvilREPL
from anvil.runtime.runtime import AnvilRuntime


def main():
    load_dotenv()
    argv = sys.argv[1:]
    if argv and argv[0] in {"fetch", "code", "need-finding", "research", "coding"}:
        raise SystemExit(_main_subcommands(argv))
    raise SystemExit(_main_legacy(argv))


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


def _main_code(argv: list[str]) -> int:
    import argparse

    from anvil.services.coding import CodingConfig, CodingService

    parser = argparse.ArgumentParser(prog="anvil code", description="Run a coding task (non-interactive)")
    parser.add_argument("task")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--max-iterations", type=int, default=10)
    args = parser.parse_args(argv)

    root_path = _git_root_or_exit()

    service = CodingService(
        CodingConfig(
            root_path=root_path,
            model=args.model,
            max_iterations=args.max_iterations,
            mode="coding",
        )
    )
    result = service.run(prompt=args.task, files=list(args.files))
    if result.final_response:
        print(result.final_response)
    return 0


def _main_subcommands(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="anvil", description="Anvil - AI Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch documents from sources")
    fetch_parser.add_argument("topic")
    fetch_parser.add_argument("--source", action="append", required=True)
    fetch_parser.add_argument("--profile", default="quick")
    fetch_parser.add_argument("--max-documents", type=int, default=100)
    fetch_parser.add_argument("--data-dir", default="data/sessions")
    fetch_parser.add_argument("--deep-comments", default="auto", choices=["auto", "always", "never"])
    fetch_parser.add_argument("-v", "--verbose", action="store_true")

    code_parser = subparsers.add_parser("code", help="Run a coding task (non-interactive)")
    code_parser.add_argument("task")
    code_parser.add_argument("files", nargs="*")
    code_parser.add_argument("--model", default="gpt-4o")
    code_parser.add_argument("--max-iterations", type=int, default=10)

    need_parser = subparsers.add_parser("need-finding", help="(Stub) Need finding workflow")
    need_parser.add_argument("topic")

    research_parser = subparsers.add_parser("research", help="(Stub) Research workflow")
    research_parser.add_argument("query")

    coding_parser = subparsers.add_parser("coding", help="(Legacy) Interactive coding mode")
    coding_parser.add_argument("files", nargs="*")

    args = parser.parse_args(argv)

    if args.command == "fetch":
        fetch_argv: list[str] = [
            args.topic,
            "--profile",
            args.profile,
            "--max-documents",
            str(args.max_documents),
            "--data-dir",
            args.data_dir,
            "--deep-comments",
            args.deep_comments,
        ]
        if args.verbose:
            fetch_argv.append("--verbose")
        for src in args.source:
            fetch_argv.extend(["--source", src])
        return _main_fetch(fetch_argv)

    if args.command == "code":
        code_argv: list[str] = [
            args.task,
            *list(args.files),
            "--model",
            args.model,
            "--max-iterations",
            str(args.max_iterations),
        ]
        return _main_code(code_argv)

    if args.command in {"need-finding", "research"}:
        print("Not implemented yet. Use `anvil fetch` and `anvil code` for now.")
        return 0

    if args.command == "coding":
        return _main_legacy(["coding", *list(args.files)])

    return 1


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
        print("❌ Error: Not in a git repository")
        raise SystemExit(1)


def _main_legacy(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Anvil - AI Coding Agent with Tools")
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model to use (supports aliases: sonnet, opus, haiku, flash, deepseek)",
    )
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually edit files")
    parser.add_argument("--no-auto-commit", action="store_true", help="Don't auto-commit")
    parser.add_argument("--no-tools", action="store_true", help="Disable structured tools")
    parser.add_argument("--no-lint", action="store_true", help="Disable auto-linting after edits")
    parser.add_argument(
        "mode_or_file",
        nargs="?",
        default=None,
        help=f"Mode to run (available: {', '.join(list_modes())}); if not a mode, treated as a file",
    )
    parser.add_argument("files", nargs="*", help="Files to add to context")
    parser.add_argument("--message", "-m", help="Single prompt (non-interactive)")

    args = parser.parse_args(argv)

    config = AgentConfig(
        model=resolve_model_alias(args.model),
        stream=not args.no_stream,
        dry_run=args.dry_run,
        auto_commit=not args.no_auto_commit,
        use_tools=not args.no_tools,
        auto_lint=not args.no_lint,
    )

    root_path = _git_root_or_exit()

    mode_name = args.mode_or_file
    files = list(args.files)
    if mode_name is None:
        mode_name = "coding"
    elif mode_name not in list_modes():
        files = [mode_name] + files
        mode_name = "coding"

    mode_config = get_mode(mode_name)
    runtime = AnvilRuntime(root_path, config, mode=mode_config)

    for filepath in files:
        runtime.add_file_to_context(filepath)

    if args.message:
        print(runtime.run_prompt(args.message, files=[]))
        return 0

    repl = AnvilREPL(runtime)
    repl.run(initial_message=None)
    return 0


if __name__ == "__main__":
    main()
