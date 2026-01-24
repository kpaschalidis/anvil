from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from anvil.workflows.deep_research_types import ReportType


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


def _catalog_prompt(
    query: str,
    *,
    target_items: int,
    findings: list[dict[str, Any]],
    allowed_urls: list[str],
) -> str:
    allowed_block = _allowed_sources_block(allowed_urls, max_items=60)
    return f"""You are a research writer producing a structured catalog of service business models.

User query:
{query}

Worker findings (JSON):
{json.dumps(findings, ensure_ascii=False)}

Return ONLY valid JSON (no markdown, no code fences), in this exact shape:
{{
  "title": "string",
  "summary_bullets": ["string"],
  "items": [
    {{
      "name": "string",
      "provider": "string",
      "website_url": "https://...",
      "problem_solved": "string",
      "who_its_for": "string",
      "how_ai_is_used": "string",
      "pricing_model": "string",
      "why_evergreen": "string",
      "replicable_with": "string",
      "proof_links": ["https://..."]
    }}
  ],
  "open_questions": ["string"]
}}

Rules:
- Produce exactly {int(target_items)} items.
- Every URL field MUST be a URL from the Allowed citation URLs list below.
- Each item MUST include at least one `proof_link` URL.
- Keep text concise but specific.
- Do not invent URLs; copy them EXACTLY.

{allowed_block}
"""


def domain_for(url: str) -> str:
    try:
        return urlparse(url).netloc or ""
    except Exception:
        return ""
