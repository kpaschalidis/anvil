# Iterative Loop Design: Memo Schema & Gap Detection

This document defines the memo schema and gap detection logic for the 3-round iterative deep research loop.

## Overview

```
Round 1: Discovery → Memo 1 → Gap Detection
Round 2: Gap-Filling → Memo 2 → Gap Detection  
Round 3: Verification → Memo 3 → Synthesis
```

The **memo** is the bounded context passed between rounds. It must be:
- Small enough to fit in planner context (~2K tokens max)
- Structured enough for gap detection
- Report-type aware

---

## 1. Report Type Detection

Before the loop starts, detect the intended deliverable:

```python
from dataclasses import dataclass
from enum import Enum
import re

class ReportType(Enum):
    NARRATIVE = "narrative"
    CATALOG = "catalog"

def detect_report_type(query: str, explicit: str | None = None) -> ReportType:
    """Detect report type from query patterns or explicit override."""
    if explicit:
        return ReportType(explicit)
    
    query_lower = query.lower()
    
    catalog_patterns = [
        r"identify\s+\d+\s+",           # "identify 5 business models"
        r"find\s+\d+\s+",               # "find 3 providers"
        r"list\s+\d+\s+",               # "list 10 tools"
        r"provide.*table",              # "provide a table"
        r"for each.*include",           # "for each, include pricing"
        r"required\s+(details|fields)", # "required details: name, url"
        r"pricing.*case.?stud",         # mentions pricing + case studies
        r"provider.*website.*url",      # wants provider URLs
    ]
    
    if any(re.search(p, query_lower) for p in catalog_patterns):
        return ReportType.CATALOG
    
    return ReportType.NARRATIVE
```

---

## 2. Memo Schema

### 2.1 Base Memo (shared fields)

```python
@dataclass
class ResearchMemo:
    """Bounded context passed between rounds."""
    
    # Identity
    query: str
    report_type: ReportType
    round_index: int          # 1, 2, or 3
    
    # Budget tracking
    tasks_completed: int
    tasks_remaining: int      # max_tasks_total - tasks_completed
    
    # Coverage stats
    unique_citations: int
    unique_domains: int
    pages_extracted: int
    
    # Content (bounded)
    themes_covered: list[str]           # max 5 short bullets
    sources_summary: list[SourceEntry]  # max 20, domain-diverse
    
    # Gaps (the key part)
    gaps: list[Gap]                     # structured gaps for next round
    
    # For Round 3
    claims_to_verify: list[Claim]       # max 3 high-impact claims
```

### 2.2 Supporting Types

```python
@dataclass
class SourceEntry:
    """Compact source reference for memo."""
    url: str
    domain: str
    title: str
    has_evidence: bool        # Did we extract content from this?
    relevance: str            # "pricing" | "case_study" | "overview" | "other"

@dataclass  
class Gap:
    """A specific information gap to fill."""
    gap_type: str             # "missing_field" | "weak_evidence" | "missing_topic"
    description: str          # Human-readable description
    priority: int             # 1=high, 2=medium, 3=low
    
    # For catalog gaps
    candidate_name: str | None
    missing_fields: list[str] | None  # ["pricing", "proof_links"]
    
    # For narrative gaps
    missing_topic: str | None
    
    # Suggested action
    suggested_query: str | None

@dataclass
class Claim:
    """A claim that needs verification in Round 3."""
    claim_text: str
    source_url: str
    confidence: str           # "high" | "medium" | "low"
    verification_query: str   # Suggested search to verify
```

### 2.3 Catalog-Specific: Candidate Tracking

For catalog reports, we track candidates across rounds:

```python
@dataclass
class CatalogCandidate:
    """A candidate item being researched for catalog report."""
    name: str
    provider_url: str | None
    
    # Field completion status
    fields: dict[str, FieldStatus]
    # e.g., {"pricing": FieldStatus.FOUND, "proof_links": FieldStatus.MISSING}
    
    # Evidence collected
    evidence_urls: list[str]

class FieldStatus(Enum):
    MISSING = "missing"
    PARTIAL = "partial"       # Found but weak evidence
    FOUND = "found"

@dataclass
class CatalogMemo(ResearchMemo):
    """Extended memo for catalog reports."""
    target_items: int                     # How many items user wants (e.g., 5)
    candidates: list[CatalogCandidate]    # Max 15 candidates tracked
    required_fields: list[str]            # ["pricing", "proof_links", ...]
```

---

## 3. Gap Detection Logic

### 3.1 Gap Detection Interface

```python
def detect_gaps(
    report_type: ReportType,
    round_index: int,
    worker_results: list[WorkerResult],
    previous_memo: ResearchMemo | None,
    config: DeepResearchConfig,
) -> list[Gap]:
    """Detect gaps after a round completes."""
    
    if report_type == ReportType.CATALOG:
        return _detect_catalog_gaps(round_index, worker_results, previous_memo, config)
    else:
        return _detect_narrative_gaps(round_index, worker_results, previous_memo, config)
```

### 3.2 Catalog Gap Detection

For catalog reports, gaps are **field-specific per candidate**:

```python
CATALOG_REQUIRED_FIELDS = [
    "name",
    "provider_url", 
    "problem_solved",
    "pricing_model",
    "proof_links",
]

CATALOG_OPTIONAL_FIELDS = [
    "pricing_evidence",      # URL + quote for pricing
    "target_customer",
    "ai_usage",
    "replicable_stack",
    "evergreen_reason",
]

def _detect_catalog_gaps(
    round_index: int,
    worker_results: list[WorkerResult],
    previous_memo: CatalogMemo | None,
    config: DeepResearchConfig,
) -> list[Gap]:
    """Detect missing fields for catalog candidates."""
    
    gaps = []
    
    # Extract candidates from worker outputs
    candidates = _extract_candidates_from_results(worker_results, previous_memo)
    
    # Check each candidate for missing required fields
    for candidate in candidates:
        missing = []
        weak = []
        
        for field in CATALOG_REQUIRED_FIELDS:
            status = candidate.fields.get(field, FieldStatus.MISSING)
            if status == FieldStatus.MISSING:
                missing.append(field)
            elif status == FieldStatus.PARTIAL:
                weak.append(field)
        
        # Create gaps for missing fields
        if missing:
            gaps.append(Gap(
                gap_type="missing_field",
                description=f"{candidate.name}: missing {', '.join(missing)}",
                priority=1 if "pricing_model" in missing else 2,
                candidate_name=candidate.name,
                missing_fields=missing,
                missing_topic=None,
                suggested_query=_suggest_field_query(candidate.name, missing),
            ))
        
        # Create gaps for weak evidence
        if weak:
            gaps.append(Gap(
                gap_type="weak_evidence",
                description=f"{candidate.name}: weak evidence for {', '.join(weak)}",
                priority=2,
                candidate_name=candidate.name,
                missing_fields=weak,
                missing_topic=None,
                suggested_query=_suggest_verification_query(candidate.name, weak),
            ))
    
    # Check if we have enough candidates
    target = config.catalog_target_items or 5
    if len(candidates) < target * 2:  # Want 2x candidates for selection
        gaps.append(Gap(
            gap_type="missing_candidates",
            description=f"Need more candidates: have {len(candidates)}, want {target * 2}",
            priority=1,
            candidate_name=None,
            missing_fields=None,
            missing_topic=None,
            suggested_query=_suggest_discovery_query(previous_memo),
        ))
    
    # Sort by priority
    gaps.sort(key=lambda g: g.priority)
    
    # Limit to top N gaps (prevent blowup)
    return gaps[:10]


def _suggest_field_query(candidate_name: str, missing_fields: list[str]) -> str:
    """Generate search query to find missing fields."""
    if "pricing_model" in missing_fields or "pricing_evidence" in missing_fields:
        return f'"{candidate_name}" pricing cost plans'
    if "proof_links" in missing_fields:
        return f'"{candidate_name}" case study customer testimonial review'
    return f'"{candidate_name}" {" ".join(missing_fields)}'


def _suggest_verification_query(candidate_name: str, weak_fields: list[str]) -> str:
    """Generate search query to verify weak evidence."""
    return f'"{candidate_name}" reviews independent analysis'
```

### 3.3 Narrative Gap Detection

For narrative reports, gaps are **topic-based**:

```python
def _detect_narrative_gaps(
    round_index: int,
    worker_results: list[WorkerResult],
    previous_memo: ResearchMemo | None,
    config: DeepResearchConfig,
) -> list[Gap]:
    """Detect missing topics or weak coverage for narrative reports."""
    
    gaps = []
    
    # Collect covered topics from worker outputs
    covered_topics = _extract_topics_from_results(worker_results)
    
    # Use LLM to identify gaps (or rule-based heuristics)
    # Option 1: LLM-based (more accurate, costs tokens)
    # Option 2: Rule-based (faster, less accurate)
    
    # Rule-based approach:
    # Check for common narrative gaps
    
    # 1. Check domain diversity
    domains = _collect_domains_from_results(worker_results)
    if len(domains) < config.min_total_domains:
        gaps.append(Gap(
            gap_type="missing_topic",
            description="Need more diverse sources",
            priority=2,
            candidate_name=None,
            missing_fields=None,
            missing_topic="diverse_sources",
            suggested_query=None,  # Planner will figure it out
        ))
    
    # 2. Check for contradictions (hard to detect without LLM)
    
    # 3. Check coverage breadth
    if round_index == 1:
        # After round 1, check if major angles are covered
        expected_angles = ["definition", "use_cases", "challenges", "trends"]
        for angle in expected_angles:
            if angle not in covered_topics:
                gaps.append(Gap(
                    gap_type="missing_topic",
                    description=f"Missing coverage: {angle}",
                    priority=2,
                    candidate_name=None,
                    missing_fields=None,
                    missing_topic=angle,
                    suggested_query=None,
                ))
    
    return gaps[:10]
```

### 3.4 LLM-Based Gap Detection (Optional Enhancement)

For more accurate gap detection, use a small LLM call:

```python
def _detect_gaps_with_llm(
    query: str,
    report_type: ReportType,
    worker_outputs: list[str],
    model: str = "gpt-4o-mini",
) -> list[Gap]:
    """Use LLM to identify gaps in current research."""
    
    prompt = f"""You are analyzing research results to identify gaps.

Query: {query}
Report Type: {report_type.value}

Current findings:
{chr(10).join(worker_outputs[:3])}  # Truncate to save tokens

Identify 3-5 specific gaps in the research. For each gap, specify:
1. What information is missing or weak
2. Priority (1=high, 2=medium)
3. A specific search query to fill the gap

Return JSON:
{{
  "gaps": [
    {{
      "description": "...",
      "priority": 1,
      "suggested_query": "..."
    }}
  ]
}}
"""
    
    # Call LLM and parse response
    # ...
```

---

## 4. Memo Construction

### 4.1 Build Memo After Round

```python
def build_round_memo(
    query: str,
    report_type: ReportType,
    round_index: int,
    worker_results: list[WorkerResult],
    previous_memo: ResearchMemo | None,
    config: DeepResearchConfig,
) -> ResearchMemo:
    """Build memo after a round completes."""
    
    # Aggregate stats
    all_citations = _collect_all_citations(worker_results, previous_memo)
    all_domains = _collect_all_domains(all_citations)
    pages_extracted = _count_extracts(worker_results, previous_memo)
    
    # Build source summary (bounded, diverse)
    sources_summary = _build_source_summary(
        worker_results,
        previous_memo,
        max_sources=20,
        max_per_domain=3,
    )
    
    # Extract themes
    themes_covered = _extract_themes(worker_results, max_themes=5)
    
    # Detect gaps
    gaps = detect_gaps(report_type, round_index, worker_results, previous_memo, config)
    
    # Identify claims to verify (for Round 3)
    claims_to_verify = []
    if round_index == 2:
        claims_to_verify = _identify_claims_to_verify(worker_results, max_claims=3)
    
    # Tasks tracking
    tasks_completed = (previous_memo.tasks_completed if previous_memo else 0) + len(worker_results)
    tasks_remaining = config.max_tasks_total - tasks_completed
    
    if report_type == ReportType.CATALOG:
        candidates = _extract_candidates_from_results(worker_results, previous_memo)
        return CatalogMemo(
            query=query,
            report_type=report_type,
            round_index=round_index,
            tasks_completed=tasks_completed,
            tasks_remaining=tasks_remaining,
            unique_citations=len(all_citations),
            unique_domains=len(all_domains),
            pages_extracted=pages_extracted,
            themes_covered=themes_covered,
            sources_summary=sources_summary,
            gaps=gaps,
            claims_to_verify=claims_to_verify,
            target_items=config.catalog_target_items or 5,
            candidates=candidates[:15],  # Bounded
            required_fields=CATALOG_REQUIRED_FIELDS,
        )
    else:
        return ResearchMemo(
            query=query,
            report_type=report_type,
            round_index=round_index,
            tasks_completed=tasks_completed,
            tasks_remaining=tasks_remaining,
            unique_citations=len(all_citations),
            unique_domains=len(all_domains),
            pages_extracted=pages_extracted,
            themes_covered=themes_covered,
            sources_summary=sources_summary,
            gaps=gaps,
            claims_to_verify=claims_to_verify,
        )
```

### 4.2 Serialize Memo for Planner

```python
def memo_to_planner_context(memo: ResearchMemo, max_tokens: int = 2000) -> str:
    """Convert memo to bounded string for planner prompt."""
    
    lines = [
        f"## Research Memo (Round {memo.round_index})",
        f"Query: {memo.query}",
        f"Report Type: {memo.report_type.value}",
        "",
        f"## Progress",
        f"- Tasks completed: {memo.tasks_completed}",
        f"- Tasks remaining: {memo.tasks_remaining}",
        f"- Unique citations: {memo.unique_citations}",
        f"- Unique domains: {memo.unique_domains}",
        f"- Pages extracted: {memo.pages_extracted}",
        "",
        f"## Themes Covered",
    ]
    
    for theme in memo.themes_covered[:5]:
        lines.append(f"- {theme}")
    
    lines.append("")
    lines.append("## Gaps to Fill")
    
    for gap in memo.gaps[:5]:
        lines.append(f"- [{gap.priority}] {gap.description}")
        if gap.suggested_query:
            lines.append(f"  Suggested: {gap.suggested_query}")
    
    if isinstance(memo, CatalogMemo):
        lines.append("")
        lines.append(f"## Candidates ({len(memo.candidates)}/{memo.target_items * 2} target)")
        for c in memo.candidates[:10]:
            missing = [f for f, s in c.fields.items() if s == FieldStatus.MISSING]
            status = "✓" if not missing else f"missing: {', '.join(missing)}"
            lines.append(f"- {c.name}: {status}")
    
    if memo.claims_to_verify:
        lines.append("")
        lines.append("## Claims to Verify (Round 3)")
        for claim in memo.claims_to_verify[:3]:
            lines.append(f"- {claim.claim_text}")
            lines.append(f"  Source: {claim.source_url}")
            lines.append(f"  Verify with: {claim.verification_query}")
    
    return "\n".join(lines)
```

---

## 5. Round-Aware Planning Prompts

### 5.1 Round 2 Planning (Gap-Filling)

```python
def _round2_planning_prompt(memo: ResearchMemo, max_tasks: int) -> str:
    memo_context = memo_to_planner_context(memo)
    
    if memo.report_type == ReportType.CATALOG:
        return f"""You are a research orchestrator planning Round 2 (gap-filling) for a CATALOG report.

{memo_context}

Your goal: Fill the identified gaps to complete candidate profiles.

Return ONLY valid JSON:
{{
  "tasks": [
    {{
      "id": "r2_task_N",
      "search_query": "specific search query",
      "instructions": "what to find and extract",
      "target_gap": "which gap this addresses"
    }}
  ]
}}

Rules:
- Create {max_tasks} tasks maximum
- Each task should target a specific gap from the memo
- For missing pricing: search "{'{candidate}'} pricing cost plans"
- For missing proof: search "{'{candidate}'} case study testimonial"
- Prioritize high-priority gaps first
"""
    else:
        return f"""You are a research orchestrator planning Round 2 (gap-filling) for a NARRATIVE report.

{memo_context}

Your goal: Fill topic gaps and strengthen weak coverage areas.

Return ONLY valid JSON:
{{
  "tasks": [
    {{
      "id": "r2_task_N",
      "search_query": "specific search query",
      "instructions": "what to find and extract",
      "target_gap": "which gap this addresses"
    }}
  ]
}}

Rules:
- Create {max_tasks} tasks maximum
- Each task should target a specific gap from the memo
- Aim for diverse sources (different domains than Round 1)
"""
```

### 5.2 Round 3 Planning (Verification)

```python
def _round3_verification_prompt(memo: ResearchMemo, max_tasks: int = 2) -> str:
    memo_context = memo_to_planner_context(memo)
    
    return f"""You are a research orchestrator planning Round 3 (verification).

{memo_context}

Your goal: Verify the highest-impact claims with independent sources.

Return ONLY valid JSON:
{{
  "verification_tasks": [
    {{
      "id": "v_task_N",
      "claim_to_verify": "the specific claim being verified",
      "search_query": "search for independent verification",
      "instructions": "look for confirming or contradicting evidence"
    }}
  ]
}}

Rules:
- Create exactly {max_tasks} verification tasks
- Target claims marked for verification in the memo
- Search for INDEPENDENT sources (different domains than already used)
- Look for both confirming AND contradicting evidence
- For pricing claims: search for alternative sources, reviews, comparisons
"""
```

---

## 6. Example Flow

### Query: "Identify 5 AI business models with pricing and case studies"

**Round 1 Memo:**
```json
{
  "report_type": "catalog",
  "round_index": 1,
  "tasks_completed": 5,
  "tasks_remaining": 10,
  "unique_citations": 18,
  "candidates": [
    {"name": "Structurely", "fields": {"pricing_model": "missing", "proof_links": "missing"}},
    {"name": "Siena", "fields": {"pricing_model": "found", "proof_links": "missing"}},
    {"name": "Conversica", "fields": {"pricing_model": "partial", "proof_links": "found"}}
  ],
  "gaps": [
    {"gap_type": "missing_field", "candidate_name": "Structurely", "missing_fields": ["pricing_model", "proof_links"], "priority": 1},
    {"gap_type": "missing_field", "candidate_name": "Siena", "missing_fields": ["proof_links"], "priority": 2}
  ]
}
```

**Round 2 Tasks Generated:**
```json
{
  "tasks": [
    {"id": "r2_1", "search_query": "\"Structurely\" pricing cost plans monthly", "target_gap": "Structurely pricing"},
    {"id": "r2_2", "search_query": "\"Structurely\" case study customer testimonial", "target_gap": "Structurely proof"},
    {"id": "r2_3", "search_query": "\"Siena AI\" case study ecommerce", "target_gap": "Siena proof"}
  ]
}
```

**Round 2 Memo:**
```json
{
  "round_index": 2,
  "candidates": [
    {"name": "Structurely", "fields": {"pricing_model": "found", "proof_links": "found"}},
    {"name": "Siena", "fields": {"pricing_model": "found", "proof_links": "found"}},
    {"name": "Conversica", "fields": {"pricing_model": "found", "proof_links": "found"}}
  ],
  "gaps": [],
  "claims_to_verify": [
    {"claim_text": "Structurely costs $149-$449/month", "verification_query": "Structurely pricing review comparison"}
  ]
}
```

**Round 3 Verification Tasks:**
```json
{
  "verification_tasks": [
    {"id": "v_1", "claim_to_verify": "Structurely $149-$449/month", "search_query": "Structurely pricing review G2 Capterra"},
    {"id": "v_2", "claim_to_verify": "Siena handles 80% of customer interactions", "search_query": "Siena AI reviews performance metrics"}
  ]
}
```

---

## 7. Implementation Notes

### What This Design Does NOT Include

1. **Structured worker output** - Workers still return markdown notes. Gap detection parses them heuristically or uses LLM.
2. **Dynamic round stopping** - Fixed at 3 rounds. Early stopping can be added later.
3. **Adaptive task budgets** - Fixed caps per round. Can be made adaptive later.

### Dependencies on Existing Code

- Uses existing `WorkerResult` structure
- Uses existing `web_search_trace` and `web_extract_trace` for stats
- Uses existing synthesis pipeline (just feeds it bounded input)

### New Files to Create

```
src/anvil/workflows/
  memo.py           # ResearchMemo, CatalogMemo, Gap classes
  gap_detection.py  # detect_gaps(), _detect_catalog_gaps(), etc.
  round_loop.py     # Main loop orchestration (or modify deep_research.py)
```
