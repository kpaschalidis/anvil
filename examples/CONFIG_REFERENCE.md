# Scout Configuration Reference

Complete reference for all Scout configuration options.

## Environment Variables

### Required (LLM)

```bash
# OpenAI (recommended)
OPENAI_API_KEY=sk-proj-...

# Or Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### Optional

```bash
# Data directory (default: data/sessions)
SCOUT_DATA_DIR=/path/to/sessions

# Reddit API (requires approval at reddit.com/prefs/apps)
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
REDDIT_USER_AGENT=scout/0.1
```

---

## CLI Flags

### `scout run` - Main Research Command

```bash
uv run scout run <topic> [options]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--profile` | `quick\|standard\|deep` | `standard` | Research profile preset |
| `--source` | string | `hackernews` | Comma-separated sources |
| `--max-iterations` | int | 60 | Max search iterations |
| `--max-documents` | int | 200 | Max documents to collect |
| `--max-cost` | float | None | Budget limit in USD |
| `--parallel-workers` | int | 5 | Concurrent search tasks |
| `--extraction-prompt` | string | `v1` | Extraction prompt version |
| `--resume` | string | None | Resume session by ID |
| `--log-format` | `text\|json` | `text` | Log output format |
| `--verbose` | flag | False | Enable debug logging |

**Examples:**

```bash
# Quick research with $1 budget
uv run scout run "CRM tools" --profile quick --max-cost 1.0

# Deep research with custom limits
uv run scout run "topic" --profile deep \
  --max-iterations 100 \
  --max-documents 300 \
  --parallel-workers 8

# Use improved extraction prompt
uv run scout run "topic" --extraction-prompt v2

# Resume paused session
uv run scout run --resume abc123
```

---

## Research Profiles

Pre-configured presets for common use cases.

### Quick Profile
```python
{
    "max_iterations": 20,
    "max_documents": 50,
    "saturation_threshold": 0.3,
    "parallel_workers": 3,
}
```
**Best for:** Initial topic validation  
**Time:** 5-10 minutes  
**Cost:** ~$0.10

### Standard Profile (default)
```python
{
    "max_iterations": 60,
    "max_documents": 200,
    "saturation_threshold": 0.2,
    "parallel_workers": 5,
}
```
**Best for:** Most use cases  
**Time:** 15-30 minutes  
**Cost:** ~$0.50

### Deep Profile
```python
{
    "max_iterations": 150,
    "max_documents": 500,
    "saturation_threshold": 0.15,
    "parallel_workers": 8,
    "deep_comments": "always",
}
```
**Best for:** Comprehensive research  
**Time:** 1-2 hours  
**Cost:** ~$2-5

---

## ScoutConfig Object

When using the Python API, configure via `ScoutConfig`:

```python
from scout.config import ScoutConfig

# Use a profile
config = ScoutConfig.from_profile("standard")

# Or fully custom
config = ScoutConfig(
    # Limits
    max_iterations=60,
    max_documents=200,
    max_cost_usd=2.0,
    
    # Performance
    parallel_workers=5,
    
    # Saturation detection
    saturation_threshold=0.2,
    saturation_window=10,
    saturation_empty_extractions_limit=5,
    saturation_signal_diversity_threshold=0.6,
    saturation_min_entities=20,
    
    # Comments depth
    deep_comments="auto",  # "auto" | "always" | "never"
    
    # Filtering (see below)
    filter=FilterConfig(...),
    snippet_validation=SnippetValidationConfig(...),
    
    # LLM settings
    llm=LLMConfig(...),
)
```

---

## FilterConfig - Content Pre-Filtering

Filter documents **before** sending to LLM (saves cost):

```python
from scout.filters import FilterConfig

filter = FilterConfig(
    min_content_length=100,    # Skip posts with < 100 chars
    min_score=5,               # Skip posts with score < 5
    skip_deleted_authors=True  # Skip [deleted] authors
)
```

**Use when:**
- You want to skip low-quality/short content
- Budget is tight
- You only care about popular posts

---

## SnippetValidationConfig - Post-Extraction Filtering

Filter snippets **after** LLM extraction (ensures quality):

```python
from scout.validation import SnippetValidationConfig

validation = SnippetValidationConfig(
    min_confidence=0.5,           # Drop snippets with confidence < 0.5
    min_excerpt_length=10,        # Drop snippets with short excerpts
    min_pain_statement_length=10  # Drop snippets with short pain statements
)
```

**Use when:**
- LLM is producing noisy/low-quality extractions
- You want only high-confidence results
- Post-processing cleanup

---

## LLMConfig - Model Settings

```python
from scout.config import LLMConfig

llm = LLMConfig(
    model="gpt-4o",                     # Default model
    extraction_model="gpt-4o",          # Model for extraction
    extraction_prompt_version="v1",     # Prompt version (v1 or v2)
    complexity_model="gpt-4o-mini",     # Model for complexity assessment
    temperature=0.0,                    # Deterministic output
    max_tokens=4096,                    # Max tokens per request
)
```

**Model recommendations:**
- **Cost-optimized:** `gpt-4o-mini` for extraction
- **Quality-optimized:** `gpt-4o` or `claude-sonnet-4` for extraction
- **Complexity:** Always use `gpt-4o-mini` (cheap, good enough)

---

## Saturation Detection Parameters

Controls when the agent decides "enough data collected":

```python
config = ScoutConfig(
    # Novelty threshold
    saturation_threshold=0.2,  # Stop if avg novelty < 0.2
    saturation_window=10,      # Look at last 10 extractions
    
    # Empty extraction window
    saturation_empty_extractions_limit=5,  # Stop if last 5 extractions empty
    
    # Diversity requirements
    saturation_signal_diversity_threshold=0.6,  # Need 60% signal type coverage
    saturation_min_entities=20,                 # Need at least 20 unique entities
)
```

**Lower thresholds** = more exhaustive search (higher cost)  
**Higher thresholds** = faster stop (lower coverage)

---

## Data Directories

```python
config = ScoutConfig(
    data_dir="data/sessions"  # Where to store session data
)
```

**Session directory structure:**
```
data/sessions/<session_id>/
├── state.json          # Session state (resumable)
├── session.db          # SQLite database
├── raw.jsonl           # Raw documents (optional)
├── snippets.jsonl      # Extracted snippets
└── events.jsonl        # Agent decision log
```

---

## Extraction Prompts

### v1 (default)
Basic prompt without examples.

### v2 (recommended)
Includes few-shot examples for better extraction quality.

**Usage:**
```bash
# CLI
uv run scout run "topic" --extraction-prompt v2

# Python
config.llm.extraction_prompt_version = "v2"
```

**When to use v2:**
- Default extractions are too noisy
- You need higher precision
- Domain-specific pain point patterns

---

## Complete Example

Putting it all together:

```python
from scout.config import ScoutConfig, LLMConfig
from scout.filters import FilterConfig
from scout.validation import SnippetValidationConfig

config = ScoutConfig(
    # Limits
    max_iterations=40,
    max_documents=150,
    max_cost_usd=1.5,
    
    # Performance
    parallel_workers=6,
    
    # Pre-filtering
    filter=FilterConfig(
        min_content_length=150,
        min_score=8,
        skip_deleted_authors=True
    ),
    
    # Post-filtering
    snippet_validation=SnippetValidationConfig(
        min_confidence=0.7,
        min_excerpt_length=15,
        min_pain_statement_length=20
    ),
    
    # LLM
    llm=LLMConfig(
        extraction_model="gpt-4o",
        extraction_prompt_version="v2",
        temperature=0.0
    ),
    
    # Saturation
    saturation_threshold=0.18,
    saturation_min_entities=25,
    
    # Other
    deep_comments="auto",
    data_dir="data/sessions"
)
```

---

## Performance Tuning

### Maximize Speed
```python
config = ScoutConfig(
    parallel_workers=10,              # More workers
    deep_comments="never",            # Skip comment depth
    filter=FilterConfig(
        min_content_length=200,       # Skip short content
        min_score=15                  # Only popular posts
    ),
    llm=LLMConfig(
        extraction_model="gpt-4o-mini"  # Fast model
    )
)
```

### Maximize Quality
```python
config = ScoutConfig(
    deep_comments="always",          # Always fetch deep comments
    filter=FilterConfig(
        min_content_length=50,        # Don't skip too much
        min_score=3
    ),
    snippet_validation=SnippetValidationConfig(
        min_confidence=0.8            # High quality only
    ),
    llm=LLMConfig(
        extraction_model="gpt-4o",
        extraction_prompt_version="v2"
    ),
    saturation_threshold=0.15        # More thorough
)
```

### Minimize Cost
```python
config = ScoutConfig(
    max_cost_usd=0.25,               # Hard budget
    filter=FilterConfig(
        min_content_length=300,       # Aggressive filtering
        min_score=20
    ),
    llm=LLMConfig(
        extraction_model="gpt-4o-mini"  # Cheap model
    ),
    parallel_workers=3                # Fewer workers
)
```

---

## Validation

Always validate your config:

```python
config.validate(sources=["hackernews"])
```

This checks:
- API keys are set
- All numeric values are valid
- Prompt versions exist
- Source configs are valid
