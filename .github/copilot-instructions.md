# Anvil Codebase - Copilot Instructions

## Overview

**Anvil** is a multi-agent AI coding framework with two main components:
- **Anvil**: An interactive AI coding agent with structured tool support, supporting 100+ models via LiteLLM
- **Scout**: A research agent that discovers pain points from online sources (Hacker News, Product Hunt, Reddit, GitHub)

Both agents follow a command-loop architecture with tool-based execution and support resumable sessions.

## Architecture

### Core Components

**`src/anvil/`** - Main coding agent framework
- `runtime/runtime.py`: Central orchestrator handling tools, history, file management, and markdown execution
- `agent.py`: Legacy agent (deprecated in favor of runtime)
- `cli.py`: Entry point; loads `.env`, parses model aliases, dispatches to modes
- `tools/registry.py`: Tool registry pattern - tools are registered with name, schema, and callable
- `history.py`: `MessageHistory` manages chat history with role-based messages and tool results
- `parser.py`: `ResponseParser` extracts edits from model responses using SEARCH/REPLACE regex pattern

**`src/scout/`** - Research discovery agent
- `agent.py` (`IngestionAgent`): Core loop managing extraction, parallel search, cost tracking
- `session.py` (`SessionManager`): Resumable session management with state persistence
- `pipeline.py` (`ExtractionPipeline`): Content filtering → LLM extraction → validation
- `extract.py` (`Extractor`): LLM-based pain point extraction with retries
- `storage.py`: JSONL-based persistence (documents, snippets, events)
- `parallel.py`: Multi-worker concurrent source searching with result aggregation
- `filters.py`: Content filtering (duplication, quality, language)
- `validation.py`: Snippet validation and deduplication
- `circuit_breaker.py`: Per-source failure tracking to avoid rate-limit exhaustion

**`src/common/`** - Shared utilities
- `llm.py`: LiteLLM wrapper handling multi-model support, streaming, tool calls, cost calculation
- `ids.py`: ID generation
- `jsonio.py`: JSON file I/O
- `text_template.py`: Template rendering

### Modes System

**`src/anvil/modes/`** - Extensible mode architecture
- Modes customize behavior: config defaults, tool registration, session namespacing, REPL commands
- `ModeConfig` dataclass with hooks: `apply_defaults`, `register_tools`, `extend_builtins`
- Sessions namespaced under `.anvil/sessions/<namespace>/` with legacy fallback
- Example: `modes/coding/` registers coding-specific tools (`git_status`, `git_diff`, `apply_edit`)

### Runtime Extensions

**`src/anvil/runtime/`** - Modern runtime architecture
- `runtime.py`: Manages tools, markdown execution, subagent coordination
- `hooks.py` (`RuntimeHooks`): Pub/sub pattern for lifecycle events (pre_edit, post_edit, etc.)
- `builtins.py`: Built-in REPL commands (`/add`, `/drop`, `/files`, `/git`, `/undo`, etc.)
- Supports markdown code block execution with language detection

### Sessions & State

- **Anvil**: `.anvil/sessions/<namespace>/<session_id>/` stores committed changes
- **Scout**: `data/sessions/<session_id>/` stores `state.json` (resumable), `raw.jsonl`, `snippets.jsonl`, `events.jsonl`
- Both use atomic JSON writes for crash safety

## Key Patterns

### Tool Registration

Tools use a registry pattern with declarative JSON schemas (OpenAI format). Always include:
```python
self.tools.register_tool(
    name="tool_name",
    description="What it does",
    parameters={"type": "object", "properties": {...}, "required": [...]},
    implementation=self._tool_implementation,
)
```
Tool implementations receive kwargs matching parameter names and return success/error dicts.

### Edit Parsing

Anvil models emit edits in SEARCH/REPLACE format (regex in `parser.py`):
```
filename.py
```python
<<<<<<< SEARCH
old code
=======
new code
>>>>>>> REPLACE
```
`ResponseParser.parse_edits()` extracts (filename, search, replace) tuples for atomic replacement.

### Message History

`MessageHistory` maintains chat state with system prompt + messages. Roles: `system`, `user`, `assistant`, `tool`.
Tool results are added with `add_tool_result(tool_call_id, name, content)`.
The API call uses `get_messages_for_api()` which prepends the system prompt.

### Configuration

- **Anvil**: `AgentConfig` dataclass (model, temperature, auto_commit, dry_run, auto_lint, etc.)
- **Scout**: `ScoutConfig` with nested source configs. Use `get_required_env()` / `get_optional_env()` for validation
- Model aliases resolve via `resolve_model_alias()`: `sonnet` → `claude-sonnet-4-20250514`

### LLM Calls

Use `common.llm.completion()` / `completion_with_usage()`:
- Auto-drops unsupported params with `litellm.drop_params = True`
- Returns response object with `.usage` attr (cost calculated via `litellm.completion_cost()`)
- Tools passed as `tools` param; `tool_choice` defaults to `"auto"`

### Scout's Saturation Detection

Scout stops iterating when novelty plateaus. Checks:
- Empty extraction ratio exceeds threshold (`saturation_empty_extractions_limit`)
- Signal type diversity below threshold (`saturation_signal_diversity_threshold`)
- Entity count plateaus (`saturation_min_entities`)
Used to avoid wasted LLM calls on exhausted topics.

## Testing

- **Location**: `tests/` mirrors `src/` structure
- **Fixtures** (`conftest.py`): `temp_repo`, `temp_file` using pytest tmpdir
- **Patterns**: Use pytest, fixtures for setup, assert on outputs
- **Run**: `uv run pytest -v` or target specific files

## Development Workflows

### Setup
```bash
uv sync                              # Install dependencies (creates .venv/)
echo "OPENAI_API_KEY=sk-..." > .env  # Add API keys
```

### Running

**Anvil (coding agent)**:
```bash
uv run anvil                         # Default gpt-4o, interactive REPL
uv run anvil --model sonnet          # Use Claude Sonnet
uv run anvil src/file.py             # Preload files
uv run anvil -m "Your task here"     # Initial message
uv run anvil --dry-run               # Preview changes
```

**Scout (research)**:
```bash
uv run scout run "topic"             # Research with Hacker News (default)
uv run scout run "topic" --source producthunt
uv run scout dump "topic" > raw.jsonl  # Raw docs only (no LLM)
uv run scout list                    # List sessions
uv run scout stats <session_id>      # Show stats
```

### Testing
```bash
uv run pytest tests/                 # Run all tests
uv run pytest tests/test_agent.py -v # Specific file
uv run pytest -k test_name           # Specific test
```

### Common Tasks
- **Model testing**: Use `--model` flag; aliases in `config.py`
- **Dry-run edits**: `--dry-run` parses but doesn't apply
- **Linting issues**: Auto-linting runs unless `--no-lint`; checks pytest auto-commit with `--no-auto-commit`
- **Git integration**: Built-in `/git` commands in REPL; stored in `.anvil/sessions/`

## Integration Points

### Scout Data Sources

Sources implement `Source` base class with async `search()` returning `SearchResult` (docs + metadata).
Built-in sources: HackerNews, ProductHunt, Reddit (with auth), GitHub Issues.
Registered via `pyproject.toml` entry points: `scout.sources`.

### Subagents

`src/anvil/subagents/` allows delegating tasks to sub-agents. `SubagentRunner` wraps agents as tools.
Define in `subagents/registry.py`; used for specialized tasks without context switching.

### Markdown Execution

`ext/markdown_executor.py` runs code blocks from markdown files.
Supports language detection (`python`, `bash`, etc.); results injected back into history for context.

### Prompts

`src/anvil/prompts/blocks/` contains modular prompt segments (markdown format).
`composer.py` loads and merges blocks; search order: mode-specific → core blocks.
Use `load_prompt_blocks()` to compose dynamic prompts.

## Common Pitfalls

1. **Forgetting dry_run flag**: Test complex changes with `--dry-run` before auto-commit
2. **Model aliases**: Always use short aliases (`sonnet`, `opus`, `flash`) or full names, never partial names
3. **Scout resumption**: Session state is in `data/sessions/<id>/state.json`; resume with `--resume`
4. **Tool parameter validation**: Always include `required` array in tool schemas; missing params cause tool execution failures
5. **Session isolation**: Sessions namespace by `session_namespace` in `ModeConfig`; don't mix namespaces
6. **LLM cost control**: Scout has `max_cost_usd` in config; monitor with `cost_tracker` in agent

## Key Files to Know

| File | Purpose |
|------|---------|
| `src/anvil/config.py` | Model aliases, AgentConfig |
| `src/anvil/runtime/runtime.py` | Main agent loop, tool dispatch |
| `src/anvil/history.py` | Chat state management |
| `src/anvil/parser.py` | SEARCH/REPLACE parsing |
| `src/anvil/tools/registry.py` | Tool registration pattern |
| `src/scout/agent.py` | Scout core loop & saturation logic |
| `src/scout/pipeline.py` | Content → extraction → validation |
| `src/common/llm.py` | LiteLLM wrapper |
| `src/anvil/modes/base.py` | Mode extension architecture |
| `pyproject.toml` | Entry points, dependencies, config |

## .env & Environment

Anvil auto-loads `.env` from working directory. Expected variables:
- `OPENAI_API_KEY` - for GPT models
- `ANTHROPIC_API_KEY` - for Claude models
- `GEMINI_API_KEY` - for Gemini models
- `SCOUT_DATA_DIR` - Scout session storage (default: `data/sessions`)
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` - for Reddit (optional)
- `GITHUB_TOKEN` or `GH_TOKEN` - for GitHub sources (optional)

Current branch: `feature/next-steps` | Default: `main`
