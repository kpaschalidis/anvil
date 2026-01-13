# Scout CLI - Quick Examples

All the ways to configure Scout via command-line.

## Basic Usage

```bash
# Quick research (5-10 min, ~$0.10)
uv run scout run "CRM pain points" --profile quick

# Standard research (15-30 min, ~$0.50)
uv run scout run "project management" --profile standard

# Deep research (1-2 hours, ~$2-5)
uv run scout run "enterprise tools" --profile deep
```

---

## Logging Modes

```bash
# Quiet: clean progress bar, warnings/errors only (recommended for production)
uv run scout run "topic" --quiet

# Normal: INFO logs + progress bar (default)
uv run scout run "topic"

# Verbose: DEBUG logs + periodic progress (for troubleshooting)
uv run scout run "topic" --verbose

# JSON logs (for programmatic parsing)
uv run scout run "topic" --log-format json
```

---

## Performance Control

### Parallel Workers

```bash
# Default (5 workers)
uv run scout run "topic"

# More workers = faster
uv run scout run "topic" --workers 10

# Fewer workers = more reliable under rate limits
uv run scout run "topic" --workers 3
```

### Comment Depth Strategy

```bash
# Auto (default): fetch deep comments only for high-score posts
uv run scout run "topic" --deep-comments auto

# Always: fetch all comment threads (slower, comprehensive)
uv run scout run "topic" --deep-comments always

# Never: skip comments entirely (fastest, cheapest)
uv run scout run "topic" --deep-comments never
```

---

## Content Filtering

### Filter by Length

```bash
# Skip posts shorter than 200 characters
uv run scout run "topic" --min-content-length 200

# Very aggressive filtering (500+ chars only)
uv run scout run "topic" --min-content-length 500
```

### Filter by Score

```bash
# Skip posts with score below 10
uv run scout run "topic" --min-score 10

# Only highly upvoted content
uv run scout run "topic" --min-score 50
```

### Combined Filtering

```bash
# Skip short, low-scoring posts
uv run scout run "topic" \
  --min-content-length 150 \
  --min-score 8
```

---

## LLM Configuration

### Choose Model

```bash
# Default: GPT-4o
uv run scout run "topic"

# Cheaper: GPT-4o-mini (4x cheaper, slightly lower quality)
uv run scout run "topic" --extraction-model gpt-4o-mini

# Claude Sonnet 4 (high quality)
uv run scout run "topic" --extraction-model claude-sonnet-4-20250514

# DeepSeek (very cheap)
uv run scout run "topic" --extraction-model deepseek/deepseek-chat
```

### Prompt Version

```bash
# Default: v1 (basic prompt)
uv run scout run "topic"

# v2: with few-shot examples (better extraction)
uv run scout run "topic" --extraction-prompt v2
```

---

## Cost Management

### Set Budget

```bash
# Stop at $0.50
uv run scout run "topic" --max-cost 0.5

# Higher budget for comprehensive research
uv run scout run "topic" --max-cost 5.0
```

### Minimize Cost Strategy

```bash
uv run scout run "topic" \
  --extraction-model gpt-4o-mini \
  --deep-comments never \
  --min-content-length 300 \
  --min-score 20 \
  --workers 3 \
  --max-cost 0.25
```

---

## Research Depth

### Set Limits

```bash
# Stop after 30 iterations
uv run scout run "topic" --max-iterations 30

# Collect up to 500 documents
uv run scout run "topic" --max-documents 500

# Combined
uv run scout run "topic" -i 50 -d 200
```

---

## Preset Combinations

### Fast & Cheap Research

Perfect for quick validation.

```bash
uv run scout run "topic" \
  --profile quick \
  --extraction-model gpt-4o-mini \
  --workers 10 \
  --deep-comments never \
  --min-content-length 200 \
  --min-score 10 \
  --max-cost 0.25
```

**Expected:**
- Time: 5 minutes
- Cost: ~$0.08
- Documents: ~30-40
- Quality: Good for initial exploration

### Balanced Research (Recommended)

Best for most use cases.

```bash
uv run scout run "topic" \
  --profile standard \
  --extraction-prompt v2 \
  --workers 5 \
  --deep-comments auto \
  --min-content-length 100 \
  --max-cost 1.0
```

**Expected:**
- Time: 20-30 minutes
- Cost: ~$0.50
- Documents: ~150-200
- Quality: High

### Deep & Thorough Research

Maximum coverage and quality.

```bash
uv run scout run "topic" \
  --profile deep \
  --extraction-model gpt-4o \
  --extraction-prompt v2 \
  --workers 8 \
  --deep-comments always \
  --min-content-length 50 \
  --min-score 3 \
  --max-cost 5.0
```

**Expected:**
- Time: 1-2 hours
- Cost: ~$3-5
- Documents: ~400-500
- Quality: Maximum

---

## Session Management

### Resume & Continue

```bash
# Pause with Ctrl+C, then resume
uv run scout run --resume abc123

# Resume with different settings
uv run scout run --resume abc123 \
  --max-iterations 100 \
  --deep-comments always
```

### View Progress

```bash
# List all sessions
uv run scout list

# View session stats
uv run scout stats abc123

# Watch live (in separate terminal)
uv run scout watch abc123 --stream snippets
```

### Export Data

```bash
# Export to CSV
uv run scout export abc123 --format csv -o results.csv

# Export to Markdown summary
uv run scout export abc123 --format markdown -o report.md

# Export to JSONL
uv run scout export abc123 --format jsonl
```

---

## Logging & Debugging

### Verbose Output

```bash
# Show debug logs
uv run scout run "topic" --verbose

# JSON logging for processing
uv run scout run "topic" --log-format json > research.log
```

---

## Real-World Workflows

### Validate Topic (5 min)

```bash
# Quick check: is there enough data?
uv run scout run "niche product" --profile quick

# If good results → continue with standard
uv run scout run --resume <session_id> --profile standard
```

### Budget-Constrained Research

```bash
# Maximum value for $1
uv run scout run "topic" \
  --extraction-model gpt-4o-mini \
  --extraction-prompt v2 \
  --min-content-length 150 \
  --min-score 10 \
  --max-cost 1.0
```

### Maximum Quality Research

```bash
# Spare no expense
uv run scout run "enterprise software" \
  --profile deep \
  --extraction-model gpt-4o \
  --extraction-prompt v2 \
  --deep-comments always \
  --workers 10 \
  --max-cost 10.0
```

### Daily Monitoring

```bash
# Quick daily check on a topic
uv run scout run "my product category" \
  --profile quick \
  --max-cost 0.10 \
  --min-score 20  # Only popular posts
```

---

## Troubleshooting

### Research Too Slow

```bash
# Increase workers
uv run scout run "topic" --workers 10

# Skip comments
uv run scout run "topic" --deep-comments never

# Filter aggressively
uv run scout run "topic" --min-content-length 300
```

### Research Too Expensive

```bash
# Use mini model
uv run scout run "topic" --extraction-model gpt-4o-mini

# Set hard budget
uv run scout run "topic" --max-cost 0.50

# Filter more
uv run scout run "topic" --min-content-length 200 --min-score 15
```

### Low Quality Results

```bash
# Use better model
uv run scout run "topic" --extraction-model gpt-4o

# Use v2 prompt
uv run scout run "topic" --extraction-prompt v2

# Always fetch deep comments
uv run scout run "topic" --deep-comments always

# Less aggressive filtering
uv run scout run "topic" --min-content-length 50 --min-score 3
```

---

## All Flags Reference

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--profile` | `-p` | choice | standard | quick, standard, or deep |
| `--source` | `-s` | string | hackernews | Comma-separated sources |
| `--max-iterations` | `-i` | int | 60 | Max search iterations |
| `--max-documents` | `-d` | int | 200 | Max documents to collect |
| `--max-cost` | | float | None | Budget limit USD |
| `--workers` | `-w` | int | 5 | Parallel workers |
| `--deep-comments` | | choice | auto | auto, always, never |
| `--extraction-model` | | string | gpt-4o | LLM model name |
| `--extraction-prompt` | | choice | v1 | v1 or v2 |
| `--min-content-length` | | int | 100 | Min chars filter |
| `--min-score` | | int | 5 | Min score filter |
| `--resume` | `-r` | string | None | Session ID to resume |
| `--log-format` | | choice | text | text or json |
| `--verbose` | | flag | False | Debug logging |
