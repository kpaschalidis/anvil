# Scout (fetch-only module)

Scout is used by Anvil for fetch-only capabilities (sources + storage + resumable `state.json`).

There is no Scout CLI. Use the unified `anvil` CLI:

```bash
uv sync --extra fetch
uv run anvil fetch "AI note taking" --source hackernews --source producthunt --max-documents 50
uv run anvil fetch --resume <session_id>
```

Artifacts are written under `data/sessions/<session_id>/`:

- `state.json` (resume state)
- `raw.jsonl` (raw documents)
- `session.db` (sqlite)
