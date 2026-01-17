# Scout - Product Discovery Agent

Research agent that collects pain points from online sources.

## Supported Sources

| Source | Auth Required | Status |
|--------|---------------|--------|
| **Hacker News** | None | ✅ Ready |
| Reddit | API approval needed | ⚠️ Requires approval |
| **Product Hunt** | None (Playwright) | ✅ Ready |
| **GitHub Issues** | Optional token | ✅ Ready |

## Setup

```bash
# Install with scout extras
uv sync --extra scout

# Set LLM API key (one of these)
export OPENAI_API_KEY="your_key"
# or
export ANTHROPIC_API_KEY="your_key"
```

## Usage

```bash
# Run research with Hacker News (default, no auth needed)
uv run scout run "CRM pain points"

# Dump raw documents only (no LLM)
uv run scout dump "AI note taking" --source producthunt

# If this is your first time using Playwright:
uv run playwright install chromium

# If Product Hunt blocks headless browsing, run headful (default):
# export SCOUT_PRODUCTHUNT_HEADLESS=0
#
# You can also tune:
# export SCOUT_PRODUCTHUNT_NAV_TIMEOUT_MS=30000
# export SCOUT_PRODUCTHUNT_USER_DATA_DIR=".anvil/producthunt_profile"
# export SCOUT_PRODUCTHUNT_CHANNEL="chrome"  # optional (uses installed Chrome if available)

# Or stream raw JSONL to stdout
uv run scout dump "AI note taking" --source producthunt --output - > raw.jsonl

# Specify source explicitly
uv run scout run "insurance software problems" --source hackernews

# With limits
uv run scout run "project management" --max-iterations 30 --max-documents 50

# Resume paused session
uv run scout run --resume <session_id>

# List sessions
uv run scout list

# Show session stats
uv run scout stats <session_id>

# Export data
uv run scout export <session_id> --format jsonl
```

## Data Location

Sessions stored in `data/sessions/<session_id>/`:
- `state.json` - Session state (resumable)
- `session.db` - SQLite database
- `raw.jsonl` - Raw documents
- `snippets.jsonl` - Extracted pain snippets
- `events.jsonl` - Agent decision log

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes* | - | OpenAI API key for extraction |
| `ANTHROPIC_API_KEY` | Yes* | - | Anthropic API key (alternative) |
| `SCOUT_DATA_DIR` | No | `data/sessions` | Data directory |
| `GITHUB_TOKEN` | No | - | GitHub token for higher rate limits |
| `GH_TOKEN` | No | - | Alternative GitHub token env var |

*One LLM API key required for extraction. `scout dump` does not use an LLM.

## Reddit (if approved)

Reddit now requires API approval. If you have approval:

```bash
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"
uv run scout run "topic" --source reddit
```

## Tests

```bash
uv run pytest tests/scout/ -v
```
