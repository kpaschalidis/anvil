from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from anvil.workflows.iterative_loop import ReportType, ResearchMemo, memo_to_planner_context


def _planning_prompt(query: str, *, max_tasks: int, report_type: ReportType = ReportType.NARRATIVE) -> str:
    catalog_rules = ""
    if report_type == ReportType.CATALOG:
        catalog_rules = """
- This is a CATALOG request: tasks must discover concrete providers/services and capture pricing + proof links (case studies/testimonials) with URLs.
- Prefer tasks that map to distinct categories so we can find >= 2x candidates for selection.
""".rstrip()
    return f"""You are a research orchestrator.

Goal: propose a set of web searches to answer the user query.

User query:
{query}

Return ONLY valid JSON in this exact shape:
{{
  "tasks": [
    {{
      "id": "short_id",
      "search_query": "web search query",
      "instructions": "what to look for and what to return"
    }}
  ]
}}

Rules:
- Provide 3 to {max_tasks} tasks.
- Prefer diverse angles (definitions, market map, pros/cons, recent changes, technical details).
- Each task must be answerable via web search results (URLs).
{catalog_rules}
"""


def _gap_fill_prompt(query: str, findings: list[dict[str, Any]], *, max_tasks: int) -> str:
    return f"""You are a research orchestrator.

Goal: propose follow-up web searches to fill gaps after an initial research pass.

User query:
{query}

Current findings (JSON):
{json.dumps(findings, ensure_ascii=False)}

Return ONLY valid JSON in this exact shape:
{{
  "tasks": [
    {{
      "id": "short_id",
      "search_query": "web search query",
      "instructions": "what to look for and what to return"
    }}
  ]
}}

Rules:
- Provide 0 to {max_tasks} follow-up tasks.
- Only propose tasks that address specific gaps in the current findings.
- Each task must be answerable via web search results (URLs).
		"""


def _gap_fill_prompt_from_memo(query: str, memo: ResearchMemo, *, max_tasks: int) -> str:
    return f"""You are a research orchestrator.

Goal: propose follow-up web searches to fill gaps after the previous round.

User query:
{query}

Memo (bounded context from the previous round):
{memo_to_planner_context(memo)}

Return ONLY valid JSON in this exact shape:
{{
  "gaps": [
    {{
      "gap_type": "missing_topic|weak_evidence|missing_field|missing_candidates",
      "description": "string",
      "priority": 1,
      "suggested_query": "string (optional)"
    }}
  ],
  "tasks": [
    {{
      "id": "short_id",
      "search_query": "web search query",
      "instructions": "what to look for and what to return"
    }}
  ]
}}

Rules:
- Provide 0 to {max_tasks} tasks.
- Tasks MUST address the gaps you listed (use suggested_query when appropriate).
- Prefer NEW domains and NEW query variants.
- Return ONLY raw JSON (no markdown, no code fences).
"""


def _verification_prompt_from_memo(query: str, memo: ResearchMemo, *, max_tasks: int) -> str:
    return f"""You are a research orchestrator.

Goal: propose web searches to VERIFY and corroborate the most important claims so far.

User query:
{query}

Memo (bounded context from previous rounds):
{memo_to_planner_context(memo)}

Return ONLY valid JSON in this exact shape:
{{
  "claims_to_verify": [
    {{
      "claim_text": "string",
      "source_url": "https://...",
      "confidence": "high|medium|low",
      "verification_query": "web search query"
    }}
  ],
  "tasks": [
    {{
      "id": "short_id",
      "search_query": "web search query",
      "instructions": "what to verify and what to return (must include URLs)"
    }}
  ]
}}

Rules:
- Provide 0 to {max_tasks} tasks.
- Prefer independent sources and NEW domains (not the same source_url domain).
- Seek corroboration OR contradiction (complaints, pricing changes, independent reviews).
- Return ONLY raw JSON (no markdown, no code fences).
"""


def _verification_prompt(query: str, findings: list[dict[str, Any]], *, max_tasks: int) -> str:
    return f"""You are a research orchestrator.

Goal: propose follow-up web searches to VERIFY and corroborate the most important claims from the current findings.

User query:
{query}

Current findings (JSON):
{json.dumps(findings, ensure_ascii=False)}

Return ONLY valid JSON in this exact shape:
{{
  "tasks": [
    {{
      "id": "short_id",
      "search_query": "web search query",
      "instructions": "what to verify and what to return (must include URLs)"
    }}
  ]
}}

Rules:
- Provide 0 to {max_tasks} verification tasks.
- Prefer authoritative / primary sources and new domains not heavily used already.
- Focus on high-impact, easy-to-misinfer points; explicitly seek corroboration (or contradiction).
- Each task must be answerable via web search results + extracted page reads (URLs).
"""


def _synthesis_prompt(query: str, findings: list[dict[str, Any]], *, require_quotes: bool) -> str:
    if require_quotes:
        findings_shape = """{
      "claim": "string",
      "evidence": [
        {
          "url": "https://...",
          "quote": "A short direct quote or excerpt copied from the extracted page content."
        }
      ]
    }"""
        rules = """- Every `evidence[].url` MUST be a URL present in the worker evidence/extracted sources.
- Every `evidence[].quote` MUST be copied from that URL's extracted content (no paraphrased “quotes”).
- Base claims only on information supported by the quotes + sources.
- If you cannot support a claim with evidence, omit it."""
    else:
        findings_shape = """{
      "claim": "string",
      "citations": ["https://..."]
    }"""
        rules = """- Every item in `findings[].citations` MUST be a URL present in the worker findings citations.
- Base claims only on information supported by the cited sources (use source titles/snippets in the worker findings).
- If you cannot support a claim with citations, omit it."""

    extra_rules = ""
    if not require_quotes:
        extra_rules = """
- Use as many unique citations as practical from the provided worker findings.
- Prefer sources that look like official docs/specs/references (/docs, /spec, /reference, /api, /security) or credible organizations.
- Avoid reusing the exact same citation URLs across multiple findings unless necessary.
""".rstrip()

    return f"""You are a research synthesizer.

User query:
{query}

Worker findings (JSON):
{json.dumps(findings, ensure_ascii=False)}

Return ONLY valid JSON in this exact shape:
{{
  "title": "string",
  "summary_bullets": ["string"],
  "findings": [
    {findings_shape}
  ],
  "open_questions": ["string"]
}}

Rules:
{rules}
{extra_rules}
- Be explicit about uncertainty.
"""


def _allowed_sources_block(urls: list[str], *, max_items: int = 60) -> str:
    cleaned = []
    for u in urls:
        if isinstance(u, str) and u.startswith("http"):
            cleaned.append(u)
    cleaned = cleaned[: max(0, int(max_items))]
    if not cleaned:
        return ""
    lines = ["Allowed citation URLs (you MUST cite ONLY from this list):"]
    for i, u in enumerate(cleaned, start=1):
        lines.append(f"- S{i}: {u}")
    return "\n".join(lines)


def _outline_prompt(query: str, findings: list[dict[str, Any]]) -> str:
    return f"""You are a research outline planner.

User query:
{query}

Worker findings (JSON):
{json.dumps(findings, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "sections": [
    {{
      "id": "s1",
      "title": "string",
      "task_ids": ["task1", "task2"]
    }}
  ]
}}

Rules:
- Provide 4 to 8 sections.
- Each section must reference 1+ existing task_ids from the worker findings.
- Prefer a logical structure: context → tools/workflows → pain points → compliance → recommendations → risks.
"""


def _section_findings_prompt(query: str, *, section_title: str, evidence: list[dict[str, Any]]) -> str:
    return f"""You are a research writer for one section of a report.

User query:
{query}

Section:
{section_title}

Evidence (JSON). Quotes MUST be copied from these excerpts exactly:
{json.dumps(evidence, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "findings": [
    {{
      "claim": "string",
      "evidence": [
        {{"url": "https://...", "quote": "copied excerpt"}}
      ]
    }}
  ]
}}

Rules:
- Provide 3 to 5 findings for this section (keep output compact).
- Every finding must include 1-2 evidence items (prefer 2 when possible).
- Every evidence.url must appear in the provided Evidence list.
- Every evidence.quote must be a substring copied from that URL's excerpt.
- Keep each `claim` short (<= 200 chars) and each `quote` short (<= 240 chars). If the excerpt is long, select a shorter substring.
- Return ONLY raw JSON (no markdown, no code fences).
"""


def _summary_prompt(query: str, *, claims: list[str]) -> str:
    return f"""You are a research summarizer.

User query:
{query}

Accepted claims (bullet list):
{json.dumps(claims, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "title": "string",
  "summary_bullets": ["string"],
  "open_questions": ["string"]
}}

Rules:
- Write 5 to 10 summary bullets grounded in the claims.
- Write 3 to 8 open questions for follow-up research.
"""


def _catalog_prompt(
    query: str,
    *,
    target_items: int,
    required_fields: list[str],
    evidence: list[dict[str, Any]],
) -> str:
    fields_str = ", ".join(required_fields) if required_fields else ""
    return f"""You are a research writer producing a structured catalog of service business models.

User query:
{query}

Evidence (JSON). You MUST only use URLs from this list, and every quote MUST be copied from the excerpt exactly:
{json.dumps(evidence, ensure_ascii=False)}

Return ONLY valid JSON (no markdown, no code fences), in this exact shape:
{{
  "title": "string",
  "summary_bullets": ["string"],
  "items": [
    {{
      "service_name": "string",
      "provider_name": "string",
      "provider_url": "https://...",
      "pricing": "string",
      "problem": "string",
      "ai_how": "string",
      "delivery_model": "retainer|project|usage|other",
      "evergreen_why": "string",
      "replicable_how": "string",
      "proof_urls": ["https://..."]
    }}
  ],
  "notes": "string"
}}

Rules:
- Produce exactly {target_items} items.
- Every URL field MUST be present in the evidence list URLs.
- Every item MUST include at least one `proof_url` (case study/testimonial/service page).
- If a field is unknown, write an empty string, but prefer to find it.
- Keep text concise but specific.
- Required fields for this request: {fields_str}
"""


def domain_for(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""
