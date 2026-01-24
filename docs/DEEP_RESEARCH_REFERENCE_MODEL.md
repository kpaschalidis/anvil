# Deep Research: Reference Model for Production Systems

This document explains what makes deep research "good" and how production systems (ChatGPT, Claude, Perplexity) implement it differently.

## What Defines "Deep Research"

Deep research differs from simple RAG (retrieve-and-generate) in several fundamental ways:

| Dimension | Simple RAG | Deep Research |
|-----------|------------|---------------|
| Time budget | Seconds | 5-30 minutes |
| Search depth | 1 query, top-K results | Multiple queries, iterative refinement |
| Source handling | Snippets only | Full page extraction, PDFs, images |
| Planning | None | Multi-step task decomposition |
| Verification | None | Gap detection, claim verification |
| Output | Generic summary | Structured deliverable with citations |

## The 7 Pillars of Production-Grade Deep Research

### 1. Multi-Step Planning & Task Decomposition

**What it means**: Break complex queries into sub-tasks, each with specific goals.

**How ChatGPT does it**: Uses o3 model trained via RL on browsing/reasoning tasks. Autonomously decides what to search, when to backtrack, how to react to new information.

**How Claude does it**: Agentic workflows that can spawn multiple searches building on each other. Determines what angles need deeper exploration.

**How Perplexity does it**: "Pro Search" runs multiple searches in parallel, synthesizes across results, identifies follow-up queries automatically.

**Implementation pattern**:
```
Query → Clarify Intent → Generate Sub-Tasks → Execute in Parallel → Merge → Identify Gaps → Loop
```

### 2. Evidence-First Retrieval (Not Snippet-Based)

**What it means**: Actually read pages, extract quotes, store provenance—don't just summarize search snippets.

**The problem with snippets**: Search result snippets are ~200 chars. They're SEO-optimized, not information-dense. You can't verify claims against them.

**Production approach**:
- Fetch full page content (or first 10K chars)
- Extract relevant passages with exact quotes
- Store URL + quote + context for citation
- Prefer pages with structured data (pricing pages, case studies, technical docs)

**ChatGPT's method**: Can browse PDFs, images, spreadsheets. Stores "evidence" with source metadata. Citations link to specific passages.

### 3. Reflection Loop (Gap Detection)

**What it means**: After initial research, explicitly ask "What's missing?" and generate follow-up queries.

**Why it matters**: First-pass research is always incomplete. The best systems iterate.

**The reflection prompt pattern**:
```
Given this summary about {topic}:
{current_summary}

1. What information is missing or incomplete?
2. What claims lack strong evidence?
3. What alternative perspectives weren't covered?

Generate 1-3 follow-up search queries to fill these gaps.
```

**How local-deep-researcher implements it**:
```python
def reflect_on_summary(state):
    # Identifies knowledge_gap and generates follow_up_query
    # Then loops back to web_research node
```

### 4. Strict Grounding & Citation Verification

**What it means**: Every claim must trace to a source. Hallucinated citations = hard failure.

**Three levels of grounding**:

| Level | Requirement | Use Case |
|-------|-------------|----------|
| Basic | URL must be in search results | Quick summaries |
| Standard | URL must be in allowed source set | Most reports |
| Strict | Quote must exist in extracted page content | High-stakes research |

**Implementation**:
```python
def validate_grounding(report, allowed_urls, evidence):
    for finding in report.findings:
        for citation in finding.citations:
            if citation.url not in allowed_urls:
                raise GroundingError(f"URL {citation.url} not in allowed sources")
            if strict_mode and citation.quote:
                if citation.quote not in evidence[citation.url].content:
                    raise GroundingError(f"Quote not found in source")
```

### 5. Deliverable-Aware Output (Not Generic Summaries)

**What it means**: Output structure matches user intent—narrative report vs structured catalog vs comparison matrix.

**The ChatGPT PDF you saw** produced a catalog with:
- Provider name + website
- Problem solved + target customer  
- How AI is used
- Pricing model + evidence
- Proof links (case studies, testimonials)
- Replicability notes

**Your system produced**:
- Generic narrative with vague findings
- "AI is transforming..." claims without specifics
- Missing pricing, missing proof links

**Why the difference**: ChatGPT's planner recognized this was a "catalog" request and structured tasks accordingly. Your planner generated generic exploration tasks.

**Implementation**: Detect report type from query patterns:
```python
CATALOG_PATTERNS = [
    r"identify\s+\d+\s+",      # "identify 5 business models"
    r"provide.*table",         # "provide a table of..."
    r"for each.*include",      # "for each, include pricing..."
    r"required\s+fields",      # "required fields: name, url..."
]
```

### 6. Source Curation & Quality Signals

**What it means**: Not all sources are equal. Prefer authoritative over SEO-optimized.

**Quality signals to use**:

| Signal | Weight | Example |
|--------|--------|---------|
| Domain authority | High | .gov, .edu, known publications |
| Page type | High | /pricing, /case-studies, /docs |
| Evidence extracted | Highest | Pages we actually read |
| Recency | Medium | Published date, last updated |
| Search rank | Low | Tavily/Google position |

**Implementation pattern**:
```python
def score_source(url, evidence_extracted):
    score = 0
    if url in evidence_extracted:
        score += 10  # We actually read this page
    path = urlparse(url).path.lower()
    if any(kw in path for kw in ["pricing", "case-study", "customer"]):
        score += 5
    if urlparse(url).netloc.endswith((".gov", ".edu")):
        score += 3
    return score
```

### 7. Transparency & Uncertainty

**What it means**: Show confidence levels, acknowledge gaps, expose methodology.

**What ChatGPT does**: Shows a sidebar with steps taken, sources consulted. Admits limitations.

**What to surface**:
- Which sources were actually read vs just searched
- Which fields have strong vs weak evidence
- Where claims conflict between sources
- What follow-up research was attempted

---

## How Each System Implements Deep Research

### ChatGPT Deep Research (OpenAI)

**Architecture**:
```
User Query
    ↓
Intent Clarification (asks follow-up questions if ambiguous)
    ↓
o3 Model (trained via RL on browsing/reasoning tasks)
    ↓
Tool Use: web_search, file_search, python, browser
    ↓
Multi-step execution with backtracking
    ↓
Structured Report with Citations
```

**Key differentiators**:
- **RL-trained for research**: Model learned to plan, search, backtrack through reinforcement learning
- **Tool integration**: Can run Python code, analyze spreadsheets, parse PDFs
- **Visual browser**: Can screenshot and analyze web pages
- **Long time budget**: 5-30 minutes per query

**Limitations** (per OpenAI):
- Struggles distinguishing authoritative info from rumors
- Weak confidence calibration
- Can hallucinate sources

### Claude Research (Anthropic)

**Architecture**:
```
User Query
    ↓
Web Search (must be enabled)
    ↓
Multiple searches building on each other
    ↓
Determines what angles need deeper exploration
    ↓
Structured Output (JSON schema support)
    ↓
Report with inline citations
```

**Key differentiators**:
- **Structured outputs**: Native JSON schema enforcement—reliable parsing
- **Large context window**: Can process many documents at once
- **Strong long-form writing**: Consistent tone, logical flow
- **Private document integration**: Can search across uploaded files

**Limitations**:
- Less autonomous than ChatGPT's deep research
- Requires explicit web search enablement
- No visual browser capability

### Perplexity Pro Search

**Architecture**:
```
User Query
    ↓
Query Understanding & Expansion
    ↓
Parallel Multi-Source Search
    ↓
Real-time Synthesis
    ↓
Inline Citations with Source Preview
    ↓
Follow-up Suggestions
```

**Key differentiators**:
- **Speed**: Optimized for fast answers (seconds, not minutes)
- **Source transparency**: Shows exactly which sentence came from where
- **Real-time web**: Always up-to-date information
- **Internal search**: Can search user's uploaded documents

**Limitations**:
- Prioritizes speed over depth
- Higher hallucination rate in free tier
- Concerns about robots.txt compliance

### ThinkDepth.ai (#1 on RACE Benchmark)

**Source**: https://github.com/thinkdepthai/Deep_Research

**Core Innovation - Diffusion Algorithm**:

ThinkDepth treats research like **image diffusion** - start with a "noisy" draft, iteratively "denoise" it by adding concrete information:

```
<Diffusion Algorithm>
1. Generate next research questions to address gaps in draft report
2. ConductResearch: retrieve external information (concrete delta for denoising)  
3. refine_draft_report: remove "noise" (imprecision, incompleteness)
4. CompleteResearch: only complete when ConductResearch finds no new findings
</Diffusion Algorithm>
```

**Architecture**:
```
clarify_with_user
    ↓
write_research_brief
    ↓
write_draft_report (initial noisy draft)
    ↓
┌─────────────────────────────────────┐
│  SUPERVISOR LOOP (iterative)        │
│                                     │
│  supervisor → supervisor_tools ─┐   │
│       ▲                         │   │
│       └─────────────────────────┘   │
│                                     │
│  Tools:                             │
│  - ConductResearch (spawn workers)  │
│  - refine_draft_report              │
│  - ResearchComplete (exit)          │
│  - think_tool (reflection)          │
└─────────────────────────────────────┘
    ↓
final_report_generation
```

**Key differentiators**:
- **Draft-centric iteration**: Maintains a draft report that gets refined each iteration (not just a memo)
- **Dynamic stopping**: Loop continues until `ConductResearch` finds no new findings
- **Parallel sub-agents**: Up to 3 concurrent researchers per iteration
- **Diffusion framing**: Incompleteness is "noise" to be removed through research
- **GPT-5 model**: Using the most capable model available

**Configuration**:
```python
max_researcher_iterations = 15  # Max tool calls per researcher
max_concurrent_researchers = 3  # Parallel sub-agents
```

**The Key Prompt Pattern**:
```
Your focus is to call "ConductResearch" to conduct research against the 
overall research question and call "refine_draft_report" to refine the 
draft report with new findings.

You know the research findings are complete by running ConductResearch 
to generate diverse research questions to see if you cannot find any 
new findings.
```

**Why It's #1 on RACE**:

| RACE Dimension | How ThinkDepth Excels |
|----------------|----------------------|
| Comprehensiveness | Dynamic stopping = research until saturated |
| Insight/Depth | Multiple iterations refine analysis |
| Instruction-Following | Research brief keeps focus |
| Readability | Draft refined multiple times |

**Limitations**:
- Unpredictable runtime (dynamic stopping)
- High cost (GPT-5 + many iterations)
- Requires good "no new findings" detection

---

## Benchmarks: RACE & FACT

### RACE (Report Quality)

**RACE** = Reference-based Adaptive Criteria-driven Evaluation

Evaluates final report quality across 4 dimensions with dynamic per-task weighting:
1. **Comprehensiveness** - Coverage breadth and depth
2. **Insight/Depth** - Quality of analysis
3. **Instruction-Following** - Adherence to requirements
4. **Readability** - Clarity and organization

Validated with ~71% agreement with human expert judgment (better than inter-expert agreement at 68%).

### FACT (Citation Quality)

**FACT** = Framework for Factual Abundance & Citation Trustworthiness

Evaluates evidence gathering and citation accuracy:
- **Citation Accuracy**: Does the cited source actually support the claim?
- **Effective Citations**: How many correctly-supported citations per task?

**Key finding from FACT**:

| System | Citation Accuracy | Effective Citations |
|--------|-------------------|---------------------|
| Perplexity Deep Research | **90.24%** (best) | Moderate |
| Gemini 2.5 Pro | Medium-high | **~111/task** (most) |
| OpenAI Deep Research | Decent | 40-80/task |

**Trade-off**: High citation volume often comes at the cost of accuracy. Getting many sources is useful for breadth, but many are weak or loosely relevant.

---

## RACE Benchmark Leaderboard (Reference)

The **RACE** (Reference-based Adaptive Criteria-driven Evaluation) benchmark evaluates deep research across 4 dimensions:
1. **Comprehensiveness** - Coverage breadth and depth
2. **Insight/Depth** - Quality of analysis
3. **Instruction-Following** - Adherence to requirements
4. **Readability** - Clarity and organization

**Top performers (as of 2026)**:

| Rank | System | RACE Score | Notes |
|------|--------|-----------|-------|
| 1 | ThinkDepth.ai | ~0.50 | Diffusion algorithm, GPT-5 |
| 1 | Tavily Research | ~0.50+ | "Outstanding across all metrics" |
| 2 | Felo Research | 0.4937 | Surpasses Gemini 2.5 Pro |
| 3 | Gemini 2.5 Pro Deep Research | 0.4888-0.4892 | Top commercial |
| 4 | Salesforce Enterprise | ~0.48+ | Enterprise-focused |
| 5 | OpenAI Deep Research | 0.4698 | Using o3 model |
| 6 | LangChain Open Deep Research | 0.4344 | Open source, GPT-4.1 |

**Key insight**: LangChain (#6) is the highest-ranked fully open source framework, and with GPT-5 jumps to 0.4943 (top tier).

---

## The Ideal Deep Research Architecture

Based on production systems, here's the reference architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER QUERY                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INTENT DETECTION                             │
│  • Report type: narrative | catalog | comparison                │
│  • Scope: broad | focused                                       │
│  • Depth: quick | deep                                          │
│  • Clarification questions if ambiguous                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       PLANNER                                   │
│  • Decompose into tasks aligned to deliverable                  │
│  • For catalog: discovery tasks + verification tasks            │
│  • For narrative: topical facets + gap-fill + verify            │
│  • Specify required evidence per task                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 PARALLEL WORKERS                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                      │
│  │ Worker 1 │  │ Worker 2 │  │ Worker N │                      │
│  │          │  │          │  │          │                      │
│  │ search   │  │ search   │  │ search   │                      │
│  │ extract  │  │ extract  │  │ extract  │                      │
│  │ evidence │  │ evidence │  │ evidence │                      │
│  └──────────┘  └──────────┘  └──────────┘                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   REFLECTION / GAP DETECTION                    │
│  • What's missing from the evidence?                            │
│  • Which claims are weakly supported?                           │
│  • Generate follow-up tasks                                     │
│  • Loop back to workers if gaps found                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   VERIFICATION ROUND                            │
│  • Verify key claims with independent sources                   │
│  • Check for contradictions                                     │
│  • Flag low-confidence findings                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SYNTHESIS                                  │
│  • Schema-driven output (matches report type)                   │
│  • Evidence-first: only include supported claims                │
│  • Grounding validation: reject hallucinated citations          │
│  • Multiple passes: outline → sections → edit                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FINAL REPORT                                 │
│  • Structured JSON + rendered Markdown                          │
│  • All citations verified against allowed sources               │
│  • Confidence/uncertainty signals included                      │
│  • Artifacts: plan, traces, evidence, synthesis input           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Implementation Patterns

### Pattern 1: Two-Stage Worker (Discovery + Verification)

For catalog-style reports:

**Stage 1 - Discovery**:
```
Search broadly for candidates
Extract provider homepages
Collect: name, URL, what they do
```

**Stage 2 - Verification**:
```
For each candidate:
  Search: "{provider} pricing"
  Search: "{provider} case study testimonial"
  Extract pricing pages
  Extract proof pages
  Fill structured fields
```

### Pattern 2: Running Summary with Reflection

From local-deep-researcher:

```python
def research_loop(topic, max_iterations):
    summary = ""
    for i in range(max_iterations):
        query = generate_query(topic, summary)
        results = web_search(query)
        summary = summarize(summary, results)
        gaps = reflect(summary, topic)
        if not gaps:
            break
        topic = gaps.follow_up_query
    return summary
```

### Pattern 3: Diffusion-Based Draft Refinement (ThinkDepth)

The #1 RACE approach - treat the draft as "noisy" and iteratively denoise:

```python
def diffusion_research(query, max_iterations):
    brief = write_research_brief(query)
    draft = write_initial_draft(brief)  # Noisy initial draft
    
    for i in range(max_iterations):
        # Generate research questions targeting gaps
        questions = identify_gaps(draft, brief)
        
        # Conduct parallel research
        findings = parallel_research(questions, max_workers=3)
        
        if not findings.has_new_information:
            break  # Saturation reached
        
        # Refine draft with new findings (denoising step)
        draft = refine_draft(draft, findings)
    
    return finalize_report(draft)
```

**Key insight**: The draft is the central artifact, not a memo. Each iteration makes the draft more precise and complete.

### Pattern 4: Schema-Driven Synthesis

```python
CATALOG_SCHEMA = {
    "items": [{
        "name": "required",
        "provider": "required", 
        "website_url": "required",
        "problem_solved": "required",
        "pricing_model": "optional",
        "pricing_evidence": {"url": "str", "quote": "str"},
        "proof_links": [{"url": "str", "type": "str"}],
    }]
}

def synthesize_catalog(candidates, schema):
    # Only include candidates with required fields
    valid = [c for c in candidates if all(c.get(f) for f in schema.required)]
    # Sort by completeness
    valid.sort(key=lambda c: count_filled_fields(c, schema), reverse=True)
    # LLM pass to polish and fill gaps
    return llm_synthesize(valid[:N], schema)
```

---

## What Separates Good from Great

| Aspect | Good | Great |
|--------|------|-------|
| Search | Multiple queries | Adaptive queries based on what's found |
| Reading | Snippets | Full page extraction with quotes |
| Planning | Fixed task list | Dynamic tasks based on evidence gaps |
| Stopping | Fixed round count | Dynamic saturation detection |
| State | Memo/summary between rounds | Draft artifact refined iteratively |
| Verification | Citation check | Independent source verification |
| Output | Generic summary | Deliverable-specific structure |
| Transparency | Source list | Confidence signals + methodology |

### The ThinkDepth Insight

The key difference between #1 RACE (ThinkDepth) and lower-ranked systems:

| Approach | How it works | Trade-off |
|----------|--------------|-----------|
| **Fixed rounds** | 2-3 predetermined research phases | Predictable cost, may stop too early |
| **Diffusion/Draft-centric** | Refine draft until no new findings | Better quality, unpredictable cost |
| **Hybrid** | Fixed rounds + early-exit on saturation | Best of both |

**Recommendation for cost-sensitive systems**: Use fixed rounds (3) but add early-exit when gap detection returns empty. This gives predictability while avoiding wasted rounds on simple queries.

---

## Recommended Reading

1. **OpenAI Deep Research announcement**: https://openai.com/index/introducing-deep-research/
2. **Claude Research docs**: https://support.anthropic.com/en/articles/11088861-using-research-on-claude-ai
3. **ThinkDepth Deep Research (#1 RACE)**: https://github.com/thinkdepthai/Deep_Research
4. **GPT-Researcher (open source)**: https://github.com/assafelovic/gpt-researcher
5. **DeepResearch-Bench (RACE/FACT benchmark)**: https://deepresearch-bench.github.io/
6. **ReportBench (evaluation)**: https://arxiv.org/abs/2508.15804
7. **DeepTRACE (audit framework)**: https://arxiv.org/abs/2509.04499
