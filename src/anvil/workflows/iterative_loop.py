from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ReportType(str, Enum):
    NARRATIVE = "narrative"
    CATALOG = "catalog"


_CATALOG_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"\bidentify\s+\d+\b",
        r"\bfind\s+\d+\b",
        r"\blist\s+\d+\b",
        r"\bfor each\b.*\binclude\b",
        r"\brequired\s+(details|fields)\b",
        r"\bprovider\b.*\bwebsite\b.*\burl\b",
        r"\bpricing\b.*\bcase.?stud",
        r"\bpricing\b.*\btestimonial",
        r"\bpricing\b.*\bretainer\b",
    )
)


def detect_report_type(query: str, *, explicit: str | None = None) -> ReportType:
    if explicit:
        v = explicit.strip().lower()
        if v in (ReportType.NARRATIVE.value, ReportType.CATALOG.value):
            return ReportType(v)
        raise ValueError(f"unknown report type: {explicit}")

    q = (query or "").strip()
    if not q:
        return ReportType.NARRATIVE

    for pat in _CATALOG_PATTERNS:
        if pat.search(q):
            return ReportType.CATALOG

    return ReportType.NARRATIVE


def detect_target_items(query: str) -> int | None:
    """
    Best-effort: infer a requested item count for catalog-style prompts.

    Examples: "identify 5 …", "list 10 …", "find 3 …".
    """
    q = (query or "").strip().lower()
    if not q:
        return None

    m = re.search(r"\b(?:identify|list|find)\s+(\d{1,3})\b", q)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except Exception:
        return None
    if n <= 0:
        return None
    return min(n, 50)


def detect_required_fields(query: str) -> list[str]:
    """
    Extract a user-declared list of required fields (if present).

    This is used for catalog prompts that include a "Required details:" section.
    Returns field labels as user-provided strings (light normalization only).
    """
    q = (query or "").strip()
    if not q:
        return []

    m = re.search(r"required details(?:\s+for[^:]+)?:\s*(.+)$", q, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return []

    block = m.group(1).strip()
    # Stop at obvious section boundaries if present.
    block = re.split(r"\n\s*(critical|notes?|market saturation|deliverable|output)\b", block, maxsplit=1, flags=re.IGNORECASE)[0]

    parts: list[str] = []
    for line in block.splitlines():
        line = line.strip(" \t-•*")
        if not line:
            continue
        # Split comma-separated lines.
        for p in line.split(","):
            p = p.strip(" \t-•*")
            if p:
                parts.append(p)

    # De-dup while keeping order.
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:30]


@dataclass(frozen=True, slots=True)
class SourceEntry:
    url: str
    domain: str
    title: str = ""
    has_evidence: bool = False
    relevance: str = "other"


@dataclass(frozen=True, slots=True)
class Gap:
    gap_type: str
    description: str
    priority: int = 2
    candidate_name: str | None = None
    missing_fields: tuple[str, ...] | None = None
    missing_topic: str | None = None
    suggested_query: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimToVerify:
    claim_text: str
    source_url: str
    confidence: str = "medium"
    verification_query: str = ""


@dataclass(frozen=True, slots=True)
class ResearchMemo:
    query: str
    report_type: ReportType
    round_index: int
    tasks_completed: int
    tasks_remaining: int
    unique_citations: int
    unique_domains: int
    pages_extracted: int
    themes_covered: tuple[str, ...] = ()
    sources_summary: tuple[SourceEntry, ...] = ()
    gaps: tuple[Gap, ...] = ()
    claims_to_verify: tuple[ClaimToVerify, ...] = ()


class FieldStatus(str, Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    FOUND = "found"


@dataclass(frozen=True, slots=True)
class CatalogCandidate:
    name: str
    provider_url: str | None = None
    fields: dict[str, FieldStatus] = field(default_factory=dict)
    evidence_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogMemo(ResearchMemo):
    target_items: int = 5
    candidates: tuple[CatalogCandidate, ...] = ()
    required_fields: tuple[str, ...] = ()


def memo_to_planner_context(memo: ResearchMemo, *, max_chars: int = 8000) -> str:
    lines: list[str] = []
    lines.append(f"## Research Memo (Round {memo.round_index})")
    lines.append(f"Report Type: {memo.report_type.value}")
    lines.append("")
    lines.append("## Progress")
    lines.append(f"- Tasks completed: {memo.tasks_completed}")
    lines.append(f"- Tasks remaining: {memo.tasks_remaining}")
    lines.append(f"- Unique citations: {memo.unique_citations}")
    lines.append(f"- Unique domains: {memo.unique_domains}")
    lines.append(f"- Pages extracted: {memo.pages_extracted}")
    lines.append("")
    if memo.themes_covered:
        lines.append("## Themes Covered")
        for t in memo.themes_covered[:5]:
            lines.append(f"- {t}")
        lines.append("")
    if memo.sources_summary:
        lines.append("## Sources Summary (bounded)")
        for s in memo.sources_summary[:20]:
            ev = " evidence" if s.has_evidence else ""
            title = f" — {s.title}" if s.title else ""
            lines.append(f"- {s.domain}{ev}: {s.url}{title}")
        lines.append("")
    if memo.gaps:
        lines.append("## Gaps to Fill")
        for g in memo.gaps[:10]:
            lines.append(f"- [P{g.priority}] {g.description}")
            if g.suggested_query:
                lines.append(f"  Suggested query: {g.suggested_query}")
        lines.append("")
    if isinstance(memo, CatalogMemo):
        lines.append(f"## Candidates ({len(memo.candidates)}/{memo.target_items * 2} target)")
        for c in memo.candidates[:10]:
            missing = [k for k, v in (c.fields or {}).items() if v == FieldStatus.MISSING]
            status = "complete" if not missing else f"missing: {', '.join(missing)}"
            lines.append(f"- {c.name}: {status}")
        lines.append("")
    if memo.claims_to_verify:
        lines.append("## Claims To Verify (Round 3)")
        for c in memo.claims_to_verify[:3]:
            lines.append(f"- {c.claim_text}")
            if c.source_url:
                lines.append(f"  Source: {c.source_url}")
            if c.verification_query:
                lines.append(f"  Verify with: {c.verification_query}")
        lines.append("")

    text = "\n".join(lines).strip() + "\n"
    if len(text) <= max_chars:
        return text
    return text[: max(0, int(max_chars))].rstrip() + "\n…(memo truncated)\n"

