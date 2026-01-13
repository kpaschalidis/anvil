# Anvil

AI coding agent with structured tool support. Built with OpenAI function calling.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

## Setup

```bash
# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (creates .venv/ automatically)
uv sync

# Set your API key
export OPENAI_API_KEY=your-key-here
```

> **Note:** `uv sync` creates a virtual environment in `.venv/`. All `uv run` commands execute inside this venv automatically.

## Usage

```bash
# Run the agent
uv run anvil

# With files pre-loaded
uv run anvil src/anvil/agent.py

# With initial message
uv run anvil -m "Add error handling to the main function"

# Options
uv run anvil --help
```

### Commands (inside the agent)

- `/add <file>` - Add file to context
- `/git status` - Show git status
- `/git diff` - Show git diff
- `/quit` - Exit

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
src/anvil/
├── cli.py          # Entry point
├── agent.py        # Main agent loop
├── config.py       # Configuration
├── tools/          # Tool registry
├── git.py          # Git operations
├── files.py        # File operations
├── shell.py        # Shell commands
├── parser.py       # Response parsing
└── history.py      # Message history
```
