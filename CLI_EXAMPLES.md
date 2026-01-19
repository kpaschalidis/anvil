# CLI Examples

## Interactive agent

```bash
uv run anvil
uv run anvil repl --model sonnet
uv run anvil repl -m "Explain this repository's architecture"
```

## Fetch (Scout sources)

```bash
uv sync --extra fetch
uv run anvil fetch "CRM pain points" --source hackernews --source reddit --max-documents 50
uv run anvil fetch --resume <session_id>
```

## Deep research (Tavily)

```bash
uv sync --extra search
export TAVILY_API_KEY="tvly-..."
uv run anvil research "What are best practices for building AI agents in 2025?"
uv run anvil research --resume <session_id>
```

## Sessions

```bash
uv run anvil sessions list
uv run anvil sessions list --kind research
uv run anvil sessions open <session_id>
```
