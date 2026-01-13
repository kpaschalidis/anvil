# Scout - Product Discovery Agent

Research agent that collects pain points from Reddit.

## Setup

```bash
# Install with scout extras
uv pip install -e ".[scout]"

# Set Reddit credentials (create app at https://reddit.com/prefs/apps)
export REDDIT_CLIENT_ID="your_client_id"
export REDDIT_CLIENT_SECRET="your_client_secret"
export REDDIT_USER_AGENT="scout/0.1 by u/your_username"  # optional
```

## Usage

```bash
# Run research on a topic
uv run scout run "insurance broker software problems"

# With limits
uv run scout run "CRM small business" --max-iterations 30 --max-documents 50

# Resume paused session
uv run scout run --resume <session_id>

# List sessions (no credentials needed)
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
| `REDDIT_CLIENT_ID` | Yes (for run) | - | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Yes (for run) | - | Reddit app secret |
| `REDDIT_USER_AGENT` | No | `scout/0.1` | Reddit user agent |
| `SCOUT_DATA_DIR` | No | `data/sessions` | Data directory |

## Tests

```bash
uv run pytest tests/scout/ -v
```
