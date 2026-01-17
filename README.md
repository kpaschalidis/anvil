# Anvil

AI coding agent with structured tool support. Built with LiteLLM for multi-model support.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- API key for your chosen provider (OpenAI, Anthropic, Google, etc.)

## Setup

```bash
# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (creates .venv/ automatically)
uv sync

# Create .env file with your API keys
echo "OPENAI_API_KEY=sk-..." > .env
```

Anvil auto-loads `.env` from the current directory. Add keys for the providers you use:

```bash
OPENAI_API_KEY=sk-...              # for gpt-4o, gpt-4
ANTHROPIC_API_KEY=sk-ant-...       # for Claude models
GEMINI_API_KEY=...                 # for Gemini models
```

### Optional: Web Search (Deep Research)

Deep research uses Tavily web search.

```bash
uv sync --extra search
export TAVILY_API_KEY="tvly-..."
```

> **Note:** `uv sync` creates a virtual environment in `.venv/`. All `uv run` commands execute inside this venv automatically.

## GUI
```bash
# Install gradio
uv sync --extra gui

# Launch
uv run anvil gui                    # Default port 7860
uv run anvil gui --port 8080        # Custom port
uv run anvil gui --share            # Public link (Gradio hosting)
```


## CLI

```bash
# Interactive agent (default model = gpt-4o)
uv run anvil

# Interactive agent with model aliases
uv run anvil repl --model sonnet
uv run anvil repl --model opus
uv run anvil repl --model flash
uv run anvil repl --model deepseek

# Use full model names
uv run anvil repl --model claude-sonnet-4-20250514
uv run anvil repl --model gemini/gemini-2.5-flash

# With files pre-loaded
uv run anvil repl src/anvil/cli.py

# With initial message
uv run anvil repl -m "Add error handling to the main function"

# Fetch raw documents (Scout sources; fetch-only)
uv sync --extra scout
uv run anvil fetch "AI note taking" --source producthunt --max-documents 50

# Resume fetch (uses `data/sessions/<id>/state.json`)
uv run anvil fetch --resume <session_id>

# Web research (orchestrator-workers; requires Tavily)
uv sync --extra search
export TAVILY_API_KEY="tvly-..."
uv run anvil research "competitive analysis of AI coding agents"

# Saved artifacts (default)
# - `data/sessions/<session_id>/meta.json`
# - `data/sessions/<session_id>/research/report.md`
# Flags: --session-id, --data-dir, --output, --no-save-artifacts, --min-citations, --best-effort

# Resume research (reruns failed workers; fails unless all succeed)
uv run anvil research --resume <session_id>

# Sessions (list/show/open)
uv run anvil sessions list
uv run anvil sessions list --kind research
uv run anvil sessions open <session_id>

# Options
uv run anvil --help
uv run anvil repl --no-lint        # Disable auto-linting
uv run anvil repl --no-auto-commit # Disable auto-commit
uv run anvil repl --dry-run        # Preview changes without applying
```

### Commands (inside the agent)

| Command | Description |
|---------|-------------|
| `/add <file>` | Add file to context |
| `/drop <file>` | Remove file from context |
| `/files` | List files in context |
| `/clear` | Clear chat history |
| `/undo` | Revert last auto-commit |
| `/model [name]` | Show or switch model |
| `/tokens` | Show token usage |
| `/git status` | Show git status |
| `/git diff` | Show git diff |
| `/help` | Show all commands |
| `/quit` | Exit |

## Supported Models

Anvil uses LiteLLM, supporting 100+ models:

| Alias | Model |
|-------|-------|
| `sonnet` | claude-sonnet-4-20250514 |
| `opus` | claude-opus-4-20250514 |
| `haiku` | claude-3-5-haiku-20241022 |
| `4o` | gpt-4o |
| `flash` | gemini/gemini-2.5-flash |
| `deepseek` | deepseek/deepseek-chat |

Or use any LiteLLM-supported model name directly.

## Features

- **Multi-model support** via LiteLLM (OpenAI, Anthropic, Google, DeepSeek, etc.)
- **Structured tools** for file operations, git, shell commands
- **Auto-linting** with automatic fix attempts for Python files
- **Auto-commit** changes with undo support
- **Streaming** responses

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests (runs inside .venv)
uv run pytest

# Run tests verbose
uv run pytest -v

# Activate venv manually (optional, for IDE integration)
source .venv/bin/activate
```

## Project Structure

```
src/
├── anvil/          # AI coding agent
│   ├── cli.py          # Entry point
│   ├── config.py       # Configuration + model aliases
│   ├── linter.py       # Python linter
│   ├── tools/          # Tool registry
│   ├── git.py          # Git operations
│   ├── files.py        # File operations
│   ├── shell.py        # Shell commands
│   ├── parser.py       # Response parsing
│   └── history.py      # Message history
│
├── scout/          # Fetch-only sources + storage (no CLI)
│   ├── services/       # FetchService
│   ├── sources/        # Data sources (HN, Reddit, PH, GitHub)
│   ├── storage.py      # Session persistence (writes raw.jsonl + sqlite)
│   └── session.py      # Fetch resume state.json
│
└── common/
    └── llm.py      # Shared LLM utilities
```

---

## Fetch (Scout sources)

Scout is now a fetch-only module (sources + storage + resumable sessions). Use `anvil fetch ...` and `anvil sessions ...`.
