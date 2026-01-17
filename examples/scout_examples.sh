#!/usr/bin/env bash
set -euo pipefail

echo "Install fetch-source dependencies:"
echo "  uv sync --extra scout"
echo
echo "Fetch examples (writes to data/sessions/<id>/):"
echo "  uv run anvil fetch \"AI note taking\" --source producthunt --max-documents 50"
echo "  uv run anvil fetch \"insurance broker\" --source hackernews --source reddit --max-documents 100"
echo "  uv run anvil fetch \"kubernetes installation problems\" --source github_issues --max-documents 100"
echo
echo "Resume fetch:"
echo "  uv run anvil fetch --resume <session_id>"
echo
echo "Sessions:"
echo "  uv run anvil sessions list --kind fetch"
echo "  uv run anvil sessions dir <session_id>"
echo
echo "Deep research (web search):"
echo "  uv sync --extra search"
echo "  export TAVILY_API_KEY=tvly-..."
echo "  uv run anvil research \"competitive analysis of AI coding agents\""

