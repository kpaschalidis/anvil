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

> **Note:** `uv sync` creates a virtual environment in `.venv/`. All `uv run` commands execute inside this venv automatically.

## GUI
```bash
# Install gradio
uv pip install 'anvil[gui]'

# Launch
anvil gui                    # Default port 7860
anvil gui --port 8080        # Custom port
anvil gui --share            # Public link (Gradio hosting)
```


## CLI

```bash
# Run with default model (gpt-4o)
uv run anvil

# Use model aliases
uv run anvil --model sonnet    # Claude Sonnet
uv run anvil --model opus      # Claude Opus
uv run anvil --model flash     # Gemini Flash
uv run anvil --model deepseek  # DeepSeek

# Use full model names
uv run anvil --model claude-sonnet-4-20250514
uv run anvil --model gemini/gemini-2.5-flash

# With files pre-loaded
uv run anvil src/anvil/agent.py

# With initial message
uv run anvil -m "Add error handling to the main function"

# Options
uv run anvil --help
uv run anvil --no-lint        # Disable auto-linting
uv run anvil --no-auto-commit # Disable auto-commit
uv run anvil --dry-run        # Preview changes without applying
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
│   ├── agent.py        # Main agent loop
│   ├── config.py       # Configuration + model aliases
│   ├── llm.py          # LiteLLM wrapper
│   ├── linter.py       # Python linter
│   ├── tools/          # Tool registry
│   ├── git.py          # Git operations
│   ├── files.py        # File operations
│   ├── shell.py        # Shell commands
│   ├── parser.py       # Response parsing
│   └── history.py      # Message history
│
├── scout/          # Product discovery agent (see below)
│   ├── agent.py        # Research agent
│   ├── extract.py      # LLM extraction
│   ├── sources/        # Data sources (HN, Reddit)
│   ├── storage.py      # Session persistence
│   └── ...
│
└── common/
    └── llm.py      # Shared LLM utilities
```

---

## Scout - Product Discovery Agent

Research pain points from online sources using LLM extraction.

### Quick Start

```bash
# 1. Install Scout dependencies
uv pip install -e ".[scout]"

# 2. Set API key (in .env or export)
export OPENAI_API_KEY="sk-..."

# 3. Run research (5-10 min, ~$0.10)
uv run scout run "CRM software pain points" --profile quick

# 4. View results
uv run scout stats <session_id>
uv run scout export <session_id> --format csv
```

### Documentation

- **[📘 Quick Start Guide](SCOUT_QUICKSTART.md)** - Complete usage examples with real workflows
- **[⚙️ Config Reference](examples/CONFIG_REFERENCE.md)** - All configuration options explained
- **[🐚 Shell Examples](examples/scout_examples.sh)** - Interactive CLI examples
- **[🐍 Python API Examples](examples/scout_python_api.py)** - Programmatic usage

### Key Features

- **Multiple sources**: Hacker News (ready), Product Hunt (scrape), GitHub Issues (API), Reddit (requires approval)
- **Smart extraction**: LLM-powered pain point identification
- **Cost management**: Budgets, filtering, adaptive scaling
- **Resumable sessions**: Pause and continue research
- **Rich exports**: CSV, JSON, Markdown summaries
- **Session management**: Tags, cloning, archiving

### Research Profiles

| Profile | Time | Cost | Best For |
|---------|------|------|----------|
| `quick` | 5-10 min | ~$0.10 | Initial validation |
| `standard` | 15-30 min | ~$0.50 | Most use cases |
| `deep` | 1-2 hours | ~$2-5 | Comprehensive research |

See [SCOUT_QUICKSTART.md](SCOUT_QUICKSTART.md) for detailed examples and workflows.
