"""Utilities for deep research workflow."""

from __future__ import annotations

import json
from typing import Any

from common import llm


def parse_json_with_retry(content: str, *, model: str) -> dict[str, Any]:
    """
    Parse JSON with a single format-only retry on failure.

    This is intentionally not a "semantic repair". It only asks the model to
    reformat the same content into valid JSON.
    """
    try:
        parsed = _extract_json_object(content)
        return parsed
    except Exception:
        pass

    resp = llm.completion(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    "This JSON is invalid or malformed.\n\n"
                    f"{content}\n\n"
                    "Return ONLY the corrected valid JSON object. "
                    "No explanation, no markdown."
                ),
            }
        ],
        temperature=0.0,
        max_tokens=1500,
    )
    return _extract_json_object((resp.choices[0].message.content or "").strip())


def _extract_json_object(content: str) -> dict[str, Any]:
    """Extract a JSON object from content, handling a single fenced code block."""
    text = (content or "").strip()
    if not text:
        raise ValueError("empty content")

    if text.startswith("```"):
        lines = text.splitlines()
        if not lines:
            raise ValueError("empty fenced block")
        # Drop opening fence line, which might be ```json.
        inner_lines: list[str] = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner_lines.append(line)
        inner = "\n".join(inner_lines).strip()
        if inner:
            text = inner

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("content is not a JSON object")
    return parsed


def select_top_findings(findings: list[dict[str, Any]], *, k: int = 10) -> list[dict[str, Any]]:
    """Select the top K findings by evidence/citation density (bounded context)."""

    def score(finding: dict[str, Any]) -> int:
        citations = finding.get("citations")
        citations_count = len(citations) if isinstance(citations, list) else 0
        evidence = finding.get("evidence")
        evidence_count = len(evidence) if isinstance(evidence, list) else 0
        return citations_count + (evidence_count * 2)

    ordered = sorted(
        [f for f in findings if isinstance(f, dict)],
        key=score,
        reverse=True,
    )
    return ordered[: max(0, int(k))]

