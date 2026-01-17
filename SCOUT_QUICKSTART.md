# Scout Agent - Quick Start Guide

## 🚀 Setup (5 minutes)

### 1. Install Dependencies

```bash
cd /Users/konstantinospaschalides/Workspace/kpaschal/projects/anvil
uv sync --extra scout
```

### 2. Set API Key

Scout uses an LLM for extraction. Set one of these:

```bash
# OpenAI (recommended for speed)
export OPENAI_API_KEY="sk-..."

# Or Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Pro tip:** Add to your `~/.zshrc` or `~/.bashrc` to persist across sessions.

### 3. Verify Setup

```bash
uv run scout --help
```

---

## 📖 Usage Examples

### Raw Dump (No LLM)

Collect raw documents only (no extraction, no API keys required):

```bash
uv run scout dump "AI note taking" --source producthunt
```

Product Hunt (requires Playwright browser install):

```bash
uv run playwright install chromium
# If Product Hunt blocks headless browsing, run headful (default):
# export SCOUT_PRODUCTHUNT_HEADLESS=0
# Optional tuning:
# export SCOUT_PRODUCTHUNT_NAV_TIMEOUT_MS=30000
# export SCOUT_PRODUCTHUNT_USER_DATA_DIR=".anvil/producthunt_profile"
# export SCOUT_PRODUCTHUNT_CHANNEL="chrome"
uv run scout dump "insurance broker" --source producthunt
```

GitHub issues (optional token recommended):

```bash
export GITHUB_TOKEN="ghp_..."
uv run scout dump "kubernetes installation problems" --source github_issues
```

### Logging Modes

Scout offers three logging modes:

**Quiet Mode** (`--quiet` or `-q`) - Clean progress bar, minimal noise
```bash
uv run scout run "CRM tools" --quiet
```
- Only warnings/errors
- Best for: Production runs, clean progress tracking

**Normal Mode** (default) - Balanced monitoring
```bash
uv run scout run "CRM tools"
```
- INFO-level logs (major events)
- Progress bar visible between logs
- Best for: General usage

**Verbose Mode** (`--verbose` or `-v`) - Full debugging detail
```bash
uv run scout run "CRM tools" --verbose
```
- DEBUG-level logs (every operation)
- Periodic progress summaries
- Best for: Troubleshooting, learning how Scout works

**Recommendation**: Use `--quiet` for clean runs, `--verbose` for debugging.

---

### Example 1: Quick Research (5-10 minutes, ~$0.10)

Find pain points about CRM software on Hacker News:

```bash
uv run scout run "CRM software pain points" --profile quick
```

**What this does:**
- Searches Hacker News for relevant discussions
- Extracts pain statements using GPT-4
- Stops after ~20 iterations or 50 documents
- Outputs session ID when done

**Output:**
```
Session: 3a4f1b2c
Documents: 47
Snippets: 23
Cost: $0.08
```

### Example 2: Standard Research (15-30 minutes, ~$0.50)

Default profile with balanced depth:

```bash
uv run scout run "project management tools" --profile standard
```

**What this does:**
- Up to 60 iterations, 200 documents
- More thorough search strategy
- Better entity-based follow-ups

### Example 3: Deep Research (1-2 hours, ~$2-5)

Comprehensive research with maximum coverage:

```bash
uv run scout run "enterprise security tools" --profile deep --max-cost 5.0
```

**What this does:**
- Up to 150 iterations, 500 documents
- Always fetches deep comment threads
- Exhaustive entity and query expansion
- Stops at $5 budget

### Example 4: Resume Interrupted Session

If you stop a session (Ctrl+C), resume it:

```bash
uv run scout run --resume 3a4f1b2c
```

---

## 🎯 Research Profiles Explained

| Profile | Iterations | Documents | Best For | Est. Time | Est. Cost |
|---------|------------|-----------|----------|-----------|-----------|
| `quick` | 20 | 50 | Initial exploration | 5-10 min | $0.10 |
| `standard` | 60 | 200 | Most use cases | 15-30 min | $0.50 |
| `deep` | 150 | 500 | Comprehensive research | 1-2 hours | $2-5 |

---

## 🔧 Advanced Options

### Set Cost Budget

```bash
uv run scout run "topic" --max-cost 2.0  # Stop at $2
```

### Use Different Extraction Prompt

```bash
uv run scout run "topic" --extraction-prompt v2  # Use prompt with few-shot examples
```

### Control Performance

```bash
# More workers for faster parallel search
uv run scout run "topic" --workers 8

# Always fetch deep comment threads
uv run scout run "topic" --deep-comments always

# Never fetch comments (faster, cheaper)
uv run scout run "topic" --deep-comments never
```

### Filter Content Aggressively

```bash
# Skip short posts and low-scoring content
uv run scout run "topic" \
  --min-content-length 200 \
  --min-score 15
```

### Use Cheaper Models

```bash
# Use GPT-4o-mini for extraction (4x cheaper)
uv run scout run "topic" --extraction-model gpt-4o-mini
```

### Custom Limits

```bash
uv run scout run "topic" \
  --max-iterations 40 \
  --max-documents 100 \
  --workers 8
```

### Combined: Fast & Cheap Research

```bash
uv run scout run "topic" \
  --profile quick \
  --extraction-model gpt-4o-mini \
  --workers 3 \
  --deep-comments never \
  --min-content-length 200 \
  --min-score 10 \
  --max-cost 0.25
```

### Combined: Deep & Thorough Research

```bash
uv run scout run "topic" \
  --profile deep \
  --extraction-model gpt-4o \
  --workers 10 \
  --deep-comments always \
  --min-content-length 50 \
  --max-cost 5.0
```

### Structured JSON Logging

```bash
uv run scout run "topic" --log-format json > research.log
```

---

## 🎛️ Complete CLI Reference

### Research Limits

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--max-iterations, -i` | int | 60 | Maximum search iterations |
| `--max-documents, -d` | int | 200 | Maximum documents to collect |
| `--max-cost` | float | None | Budget limit in USD |

### Performance & Scaling

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--workers, -w` | int | 5 | Parallel search workers |
| `--deep-comments` | auto\|always\|never | auto | Comment depth strategy |

### Content Filtering

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--min-content-length` | int | 100 | Skip documents shorter than N chars |
| `--min-score` | int | 5 | Skip documents with score below N |

### LLM Configuration

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--extraction-model` | string | gpt-4o | Model for extraction |
| `--extraction-prompt` | v1\|v2 | v1 | Prompt version |

### Session Management

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--profile, -p` | quick\|standard\|deep | standard | Research profile |
| `--resume, -r` | string | None | Resume session by ID |
| `--source, -s` | string | hackernews | Comma-separated sources |

### Logging

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--log-format` | text\|json | text | Log output format |
| `--verbose` | flag | False | Enable debug logging |

---

## 📊 Working with Results

### List All Sessions

```bash
uv run scout list
```

**Output:**
```
Session ID   Topic                    Status     Docs  Snippets  Cost
-----------  -----------------------  ---------  ----  --------  -----
3a4f1b2c     CRM software            completed    47        23  $0.08
2f9e8d1a     project management      running      12         5  $0.02
```

### View Session Statistics

```bash
uv run scout stats 3a4f1b2c
```

**Output:**
```
Session: 3a4f1b2c
Topic: CRM software pain points
Status: completed
Documents: 47
Snippets: 23
Iterations: 18
Average Novelty: 0.65
Total Cost: $0.08
Total Tokens: 45,231
```

### Export Data

#### JSONL (default, most flexible)
```bash
uv run scout export 3a4f1b2c --format jsonl --output results.jsonl
```

#### CSV (for Excel/sheets)
```bash
uv run scout export 3a4f1b2c --format csv --output results.csv
```

#### Markdown Summary
```bash
uv run scout export 3a4f1b2c --format markdown --output report.md
```

### Watch Live Progress

Monitor a running session in another terminal:

```bash
# Watch events
uv run scout watch 3a4f1b2c --stream events

# Watch snippets as they're extracted
uv run scout watch 3a4f1b2c --stream snippets
```

---

## 🏷️ Session Management

### Tag Sessions

Organize sessions with tags:

```bash
uv run scout tag 3a4f1b2c "fintech" "b2b" "Q1-2025"
```

### Clone a Session

Start a new session with same context:

```bash
uv run scout clone 3a4f1b2c --topic "similar topic"
```

**Use case:** You researched "CRM pain points" and want to pivot to "CRM alternatives" without starting from scratch.

### Archive Old Sessions

Clean up sessions older than 30 days:

```bash
uv run scout archive --days 30
```

---

## 💡 Pro Tips

### 1. Start Small
Always begin with `--profile quick` to validate your topic phrasing:

```bash
uv run scout run "your topic" --profile quick
```

If results look good → resume with more depth:

```bash
uv run scout run --resume <session_id> --max-iterations 60
```

### 2. Use Cost Budgets
Prevent runaway costs:

```bash
uv run scout run "topic" --profile deep --max-cost 3.0
```

### 3. Monitor Live
Open two terminals:
- **Terminal 1:** Run scout
- **Terminal 2:** `uv run scout watch <session_id> --stream snippets`

### 4. Filter Content Aggressively
Use CLI flags for quick filtering:

```bash
uv run scout run "topic" --min-content-length 150 --min-score 10
```

Or Python API for more control:

```python
from scout.filters import FilterConfig

config.filter = FilterConfig(
    min_content_length=150,
    min_score=10,
    skip_deleted_authors=True
)
```

### 5. Use Extraction Prompt v2
Better results with few-shot examples:

```bash
uv run scout run "topic" --extraction-prompt v2
```

---

## 🔍 Example Workflow: Full Research Cycle

```bash
# 1. Quick validation (5 min, $0.10)
uv run scout run "AI code editors" --profile quick
# → Session: abc123, looks promising!

# 2. Standard research (30 min, $0.50)
uv run scout run --resume abc123 --profile standard

# 3. Export results
uv run scout export abc123 --format csv --output ai_editors.csv

# 4. Tag for future reference
uv run scout tag abc123 "devtools" "ai" "2025-Q1"

# 5. Clone for related research
uv run scout clone abc123 --topic "AI pair programming tools"
```

---

## 🎛️ Environment Variables Reference

```bash
# Required (one of these)
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional
export SCOUT_DATA_DIR="data/sessions"  # Custom data location

# Reddit (if you have API approval)
export REDDIT_CLIENT_ID="..."
export REDDIT_CLIENT_SECRET="..."
```

---

## 📂 Data Structure

After running a session, find data at `data/sessions/<session_id>/`:

```
data/sessions/3a4f1b2c/
├── state.json          # Session state (resumable)
├── session.db          # SQLite database with documents & snippets
├── raw.jsonl           # Raw documents (optional)
├── snippets.jsonl      # Extracted pain snippets
└── events.jsonl        # Agent decision log
```

**Query SQLite directly:**

```bash
sqlite3 data/sessions/3a4f1b2c/session.db
```

```sql
-- Top pain points by intensity
SELECT pain_statement, intensity, confidence, signal_type
FROM snippets
WHERE confidence > 0.8
ORDER BY intensity DESC, confidence DESC
LIMIT 10;

-- Entity frequency
SELECT json_extract(value, '$') as entity, COUNT(*) as mentions
FROM snippets, json_each(entities)
GROUP BY entity
ORDER BY mentions DESC
LIMIT 20;
```

---

## 🚨 Troubleshooting

### "No LLM API key found"
```bash
# Check env var is set
echo $OPENAI_API_KEY

# If empty, set it
export OPENAI_API_KEY="sk-..."
```

### "Rate limit error"
Scout has built-in rate limiting, but if you hit API limits:
- Use `--parallel-workers 3` to reduce concurrency
- Add delays in `src/scout/config.py`

### "Session not found"
```bash
# List all sessions
uv run scout list

# Check data directory
ls -la data/sessions/
```

### Extraction Quality Issues
Try the v2 prompt with few-shot examples:
```bash
uv run scout run "topic" --extraction-prompt v2
```

---

## 🎓 Next Steps

1. **Read the plan:** `.cursor/plans/scout_agent_improvements_a42b1bb5.plan.md` for architecture details
2. **Check source code:** `src/scout/agent.py` to understand the extraction logic
3. **Extend sources:** Add new sources via entry points in `pyproject.toml`
4. **Customize prompts:** Edit `src/scout/prompts/extract_v2.py` for domain-specific extraction

---

## 🤝 Need Help?

- Run `uv run scout <command> --help` for any command
- Check logs in terminal (use `--verbose` for debug info)
- Inspect `events.jsonl` to see agent decisions
