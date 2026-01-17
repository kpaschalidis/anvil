# Fetch Quickstart (Scout sources via `anvil fetch`)

Scout no longer has a CLI. The Scout package is used as a fetch-only module (sources + storage + resumable sessions), exposed through the unified `anvil` CLI.

## Setup

```bash
uv sync --extra scout
```

Add any needed keys to `.env` (see `.env.example`). For example, Reddit requires `REDDIT_CLIENT_ID/SECRET/USER_AGENT`.

## Fetch

```bash
uv run anvil fetch "AI note taking" --source producthunt --max-documents 50
uv run anvil fetch "insurance broker" --source hackernews --source reddit --max-documents 100
uv run anvil fetch "kubernetes installation problems" --source github_issues --max-documents 100
```

Artifacts are written under `data/sessions/<session_id>/`:

- `state.json` (resume state)
- `raw.jsonl` (raw documents)
- `session.db` (sqlite)

## Resume

```bash
uv run anvil fetch --resume <session_id>
```

## Sessions

```bash
uv run anvil sessions list --kind fetch
uv run anvil sessions show <session_id>
uv run anvil sessions dir <session_id>
```

