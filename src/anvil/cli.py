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


if __name__ == "__main__":
    main()
