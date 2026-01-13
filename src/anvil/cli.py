import os
import sys
import argparse
import subprocess

from anvil.config import AgentConfig
from anvil.agent import CodingAgentWithTools


def main():
    parser = argparse.ArgumentParser(description="Anvil - AI Coding Agent with Tools")
    parser.add_argument("--model", default="gpt-4o", help="Model to use")
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
    parser.add_argument("files", nargs="*", help="Files to add to context")
    parser.add_argument("--message", "-m", help="Initial message")

    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    config = AgentConfig(
        model=args.model,
        stream=not args.no_stream,
        dry_run=args.dry_run,
        auto_commit=not args.no_auto_commit,
        use_tools=not args.no_tools,
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

    agent = CodingAgentWithTools(root_path, config)

    for filepath in args.files:
        agent.add_file_to_context(filepath)

    agent.run(initial_message=args.message)


if __name__ == "__main__":
    main()
