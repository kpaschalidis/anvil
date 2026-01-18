# Deep Research Systems (Anthropic/ChatGPT-style): Reference Model + Target Behaviors

This document explains how “Deep Research” products *appear* to work (Anthropic/ChatGPT/Perplexity-class), what is publicly known vs inferred, and what capabilities are required to reach similar output quality and runtime.

## What we can (and cannot) know

- **We cannot know “exactly”** how Anthropic or OpenAI implement Deep Research internally unless they publish it. Their orchestration, prompt stacks, ranking signals, and safety checks are proprietary.
- We *can* build a **high-confidence reference model** from:
  - public engineering guidance (e.g., agent-building patterns, orchestrator-workers, tool use constraints),
  - observable product behavior (runtime, iterative browsing, source usage patterns),
  - established IR/retrieval practice (search → fetch → dedupe → rank → extract → verify),
  - open-source analogues (e.g., GPT-Researcher-style pipelines: “researcher → writer → editor”).

The rest of this doc is that reference model.

## Executive summary (what makes it “Deep”)

Compared to “search-and-summarize from snippets”, Deep Research typically adds:

1. **Page reading**: open a meaningful number of pages (not just SERP snippets).
2. **Evidence extraction**: store quotes/excerpts with provenance (URL + where it came from).
3. **Iterative orchestration**: plan → read → realize gaps → re-plan → read again → verify.
4. **Grounded writing pipeline**: draft from evidence, then edit/rewrite; citations are validated.
5. **Budgeted breadth/depth**: explicit controls (time, pages, tasks, parallelism) to target 10–20 minutes.

## Reference architecture (high-level)

### Roles

Most “Deep Research” systems can be modeled as 3–5 cooperating roles:

- **Orchestrator / Planner**
  - decomposes the user query into sub-questions,
  - sets a research strategy (breadth-first vs depth-first),
  - manages budgets and termination conditions.
- **Retrievers / Workers (parallel)**
  - execute sub-questions,
  - perform search with pagination and query variants,
  - collect candidate URLs and metadata.
- **Reader / Extractor**
  - fetches page content for selected URLs,
  - extracts evidence (quotes/snippets) with minimal transformation,
  - rejects low-signal pages and continues to next candidates.
- **Verifier (optional but common in “deep”)**
  - confirms key claims with at least one independent source,
  - flags contradictions and weak evidence.
- **Writer / Editor**
  - synthesizes a structured report from evidence,
  - enforces citation rules (per-claim/per-finding),
  - performs a final style/clarity pass.

### Data structures (what makes debugging possible)

Deep systems are typically driven by persisted intermediate artifacts:

- `plan`: tasks/subquestions + intended searches + success criteria.
- `search_trace`: queries, pagination, result sets, timestamps.
- `url_pool`: deduped set of candidate URLs with metadata and ranking signals.
- `reads`: per-URL raw content (or extracted text) with hashes and truncation info.
- `evidence`: normalized evidence items:
  - `{url, title, quote/excerpt, captured_at, query_used, page, ...}`
- `claim_map` (explicit or implicit):
  - each report claim references ≥1 evidence items (ideally 2 in deep mode).

## Typical multi-round loop (why it takes 10–20 minutes)

### Round 0: Setup

- Normalize the query (scope, timeframe, audience, constraints).
- Pick a budget profile:
  - max parallelism,
  - max searches per task,
  - max reads per task,
  - max total reads,
  - max total time.

### Round 1: Breadth (coverage)

- Planner produces ~5–12 tasks (subquestions).
- Workers run in parallel:
  - query variants,
  - pagination (page 1..N),
  - collect many candidate URLs across diverse domains.
- Orchestrator enforces diversity:
  - domain caps,
  - avoid repeating the same few sites,
  - ensure “primary sources” are included when relevant (docs/specs/standards).

### Round 2: Depth (reading + evidence)

- For each task, select top-K candidate URLs (often K=3–8).
- Read pages (fetch/extract):
  - store raw content (with truncation),
  - extract 3–10 evidence excerpts per task (quotes/paraphrase boundaries).
- Stop criteria (deterministic):
  - enough evidence items collected,
  - saturation (new reads add little new info),
  - budget exhausted.

### Round 3: Gap-fill / Verification (quality)

- Planner looks at evidence + draft outline and asks:
  - “What’s missing?”
  - “Which claims are weakly supported?”
  - “What’s contradictory?”
- Spawn follow-up tasks to:
  - verify key claims with independent sources,
  - fill missing subtopics,
  - strengthen “why it matters” sections with authoritative citations.

### Round 4: Writing pipeline (why output is longer and clearer)

A common pattern (also seen in open-source pipelines):

1. **Outline** from evidence (section plan + key claims).
2. **Section drafting** (one prompt per section; uses only relevant evidence).
3. **Synthesis/summary** that merges sections and de-duplicates.
4. **Editor pass**:
   - remove repetition,
   - enforce grounding rules,
   - ensure citations per claim,
   - ensure consistent voice and formatting.

## Grounding rules (the non-negotiables)

Deep Research systems typically treat these as hard requirements:

- **No evidence, no claim**: claims must be backed by evidence collected in the run.
- **Citation integrity**: cited URLs must match the retrieved/allowed URL set.
- **Quote integrity (when used)**: quotes must be copied from extracted page text, not invented.
- **Attribution correctness**: a citation must support the claim it’s attached to (not just “related”).

Coverage targets (number of sources/domains) are usually “best-effort” in fast modes, but grounding is strict.

## What controls report length

Report length in Deep Research systems is usually controlled by:

- **Outline size** (number of sections/subsections).
- **Per-section token budgets** (explicit “~N bullets” or “~N paragraphs”).
- **Findings count** (fixed number of findings vs “as many as supported”).
- **Evidence density rules** (e.g., 2 citations per claim yields more content).
- **Reader budget** (more reads → more evidence → more defensible claims → longer report).
- **Editor constraints** (dedupe and concision can shorten output even with lots of evidence).

If you only read a small number of pages, the system will naturally converge to a shorter, more generic report.

## Mapping to Anvil today (what we have vs what’s missing)

Anvil already has:

- **Search**: Tavily web search with pagination controls.
- **Workers**: parallel orchestrator-workers pattern.
- **Optional reads**: `web_extract` exists and can collect raw content (deep-mode).
- **Strict citation grounding**: the report can hard-fail if it cites URLs not in the allowed set.
- **Artifacts**: plans, traces, per-worker outputs, report JSON/MD.

What’s still missing to reach Anthropic/ChatGPT-level:

- **Read-heavy depth mode by default** (substantially more `web_extract` calls / pages read).
- **Evidence-first synthesis** (claims tied to extracted excerpts, not primarily to search snippets).
- **Verification round** that targets weak claims and contradictions.
- **Stronger writing pipeline** (section drafts + editor pass) with explicit length targets.
- **Stop conditions based on evidence saturation** (not just “min counts”).

## Practical “target behaviors” (how we’ll know we’re close)

When we’re near Anthropic/ChatGPT deep-research quality, a typical deep run should show:

- dozens of search calls across tasks and rounds,
- **meaningful read volume** (e.g., 20–60 page extracts depending on budgets),
- evidence items per major claim (often 2+ independent sources),
- a report that is:
  - more structured (sections/subsections),
  - longer (because it can defend more claims),
  - less generic (because it’s grounded in concrete excerpts),
  - reproducible (artifacts show exactly what was read and used).

## Suggested next step (implementation direction)

If the goal is Anthropic/ChatGPT-level deep research, the next “big swing” is:

- Make **deep profile** explicitly “read + extract evidence + verify + write + edit” (with budgets),
- Keep **quick profile** as fast search-and-summarize but still strictly grounded.

## Notes on budgets (Anvil-specific)

- In Anvil, the deep profile can optionally **continue** some tasks to spend remaining budget and improve coverage. When enabled, budgets like `max_web_search_calls` and `max_web_extract_calls` should be interpreted as **per-task totals across continuation attempts**, not “per attempt”, so time/cost stay predictable.
