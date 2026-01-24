from __future__ import annotations

import json
from typing import Any

from common import llm

from anvil.workflows.deep_research_prompts import _allowed_sources_block, _catalog_prompt, _synthesis_prompt
from anvil.workflows.deep_research_types import ReportType, SynthesisError, detect_target_items
from anvil.workflows.deep_research_utils import parse_json_with_retry


class DeepResearchSynthesisMixin:
    def _catalog_synthesize_and_render(
        self,
        query: str,
        *,
        findings: list[dict[str, Any]],
        citations: list[str],
    ) -> tuple[str, dict[str, Any]]:
        allowed = {u for u in citations if isinstance(u, str) and u.startswith("http")}
        target_items = detect_target_items(query) or 5

        prompt = _catalog_prompt(
            query,
            target_items=int(target_items),
            findings=findings,
            allowed_urls=sorted(allowed),
        )
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1400,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            raise SynthesisError("Catalog synthesis returned an empty response", raw=raw, stage="synthesize")

        payload = parse_json_with_retry(raw, model=self.config.model)
        self._validate_catalog_shape(payload, target_items=int(target_items), allowed_urls=allowed)

        md = self._render_catalog_payload(payload=payload, citations=sorted(allowed), evidence=[])
        return md, payload

    def _validate_catalog_shape(self, payload: dict[str, Any], *, target_items: int, allowed_urls: set[str]) -> None:
        items = payload.get("items")
        if not isinstance(items, list):
            raise SynthesisError("Catalog output missing 'items' list", raw=json.dumps(payload, ensure_ascii=False))
        if len(items) != int(target_items):
            raise SynthesisError(
                f"Expected {int(target_items)} items, got {len(items)}",
                raw=json.dumps(payload, ensure_ascii=False),
            )
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise SynthesisError(f"Item {idx} is not an object", raw=json.dumps(payload, ensure_ascii=False))
            name = item.get("name")
            website_url = item.get("website_url")
            if not isinstance(name, str) or not name.strip():
                raise SynthesisError(f"Item {idx} missing name", raw=json.dumps(payload, ensure_ascii=False))
            if not isinstance(website_url, str) or website_url not in allowed_urls:
                raise SynthesisError(
                    f"Item {idx} website_url must be one of the allowed URLs",
                    raw=json.dumps(payload, ensure_ascii=False),
                )
            proof = item.get("proof_links") or []
            proof_urls = [u for u in proof if isinstance(u, str) and u in allowed_urls]
            if not proof_urls:
                raise SynthesisError(
                    f"Item {idx} missing proof_links from allowed URLs",
                    raw=json.dumps(payload, ensure_ascii=False),
                )
    def _synthesize_and_render(
        self,
        query: str,
        findings: list[dict[str, Any]],
        citations: list[str],
        *,
        report_type: ReportType = ReportType.NARRATIVE,
    ) -> tuple[str, dict[str, Any] | None]:
        if report_type == ReportType.CATALOG:
            md, payload = self._catalog_synthesize_and_render(query, findings=findings, citations=citations)
            return md, payload

        prompt = self._synthesis_prompt_with_constraints(query, findings, allowed_urls=citations)
        payload: dict[str, Any] | None = None
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = (resp.choices[0].message.content or "").strip()
        last_err: Exception | None = None
        if raw:
            try:
                payload = parse_json_with_retry(raw, model=self.config.model)
            except Exception as e:
                last_err = e

        if payload is None and not self.config.best_effort:
            detail = f": {last_err}" if last_err else ""
            raise SynthesisError(f"Synthesis returned invalid JSON{detail}", raw=raw, stage="synthesize")

        if payload is not None:
            payload = self._validate_synthesis_payload(payload=payload, allowed_urls=set(citations))

        md = self._render_from_payload(query=query, findings=findings, citations=citations, payload=(payload or {}))
        return md, payload

    def _validate_synthesis_payload(
        self,
        *,
        allowed_urls: set[str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        issues = self._synthesis_payload_grounding_issues(payload, allowed_urls=allowed_urls)
        if issues:
            raise SynthesisError(
                "Synthesis produced citations not present in allowed sources",
                raw=json.dumps(payload, ensure_ascii=False),
                stage="synthesize",
            )

        return payload

    def _synthesis_prompt_with_constraints(
        self,
        query: str,
        findings: list[dict[str, Any]],
        *,
        allowed_urls: list[str],
    ) -> str:
        prompt = _synthesis_prompt(
            query,
            findings,
            require_quotes=bool(self.config.require_quote_per_claim),
        )
        if not self.config.require_quote_per_claim:
            min_unique = max(0, int(self.config.report_min_unique_citations_target))
            min_domains = max(0, int(self.config.report_min_unique_domains_target))
            findings_target = max(1, int(self.config.report_findings_target))
            target_per_finding = 2 if len(allowed_urls) >= findings_target * 2 else 1
            prompt = (
                prompt.rstrip()
                + "\n\n"
                + "Additional constraints for this run:\n"
                + f"- Write up to {findings_target} findings.\n"
                + f"- Target >= {min_unique} unique citation URLs across the whole report (if possible).\n"
                + f"- Target >= {min_domains} unique domains across the whole report (if possible).\n"
                + f"- Target >= {target_per_finding} citation URLs per finding (if possible).\n"
                + "- Avoid repeating the same citation URLs across multiple findings when alternatives exist.\n"
                + "- Copy citation URLs EXACTLY; do not invent or modify URLs.\n"
            )
            allowed_block = _allowed_sources_block(allowed_urls, max_items=60)
            if allowed_block:
                prompt = prompt.rstrip() + "\n\n" + allowed_block + "\n"
        return prompt

    def _synthesis_payload_grounding_issues(self, payload: dict[str, Any], *, allowed_urls: set[str]) -> list[str]:
        findings = payload.get("findings")
        if not isinstance(findings, list):
            return ["payload.findings is missing or not a list"]
        bad: set[str] = set()
        for it in findings:
            if not isinstance(it, dict):
                continue
            cites = it.get("citations") or []
            if not isinstance(cites, list):
                continue
            for c in cites:
                if isinstance(c, str) and c.startswith("http") and c not in allowed_urls:
                    bad.add(c)
        if not bad:
            return []
        sample = sorted(bad)[:5]
        return [f"found {len(bad)} citation(s) not in allowed sources: {', '.join(sample)}"]
