from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from common import llm
from common.events import ProgressEvent

from anvil.workflows.deep_research_prompts import _allowed_sources_block, _synthesis_prompt
from anvil.workflows.deep_research_types import SynthesisError
from anvil.workflows.iterative_loop import ReportType


class DeepResearchSynthesisMixin:
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

        if self.config.require_quote_per_claim and self.config.multi_pass_synthesis and not self.config.best_effort:
            md, payload = self._multi_pass_synthesize_and_render(query, findings, citations)
            return md, payload

        prompt = self._synthesis_prompt_with_constraints(query, findings, allowed_urls=citations)
        payload: dict[str, Any] | None = None
        raw = ""
        last_err: Exception | None = None
        for attempt in range(2):
            resp = llm.completion(
                model=self.config.model,
                messages=(
                    [{"role": "user", "content": prompt}]
                    if attempt == 0 or not raw
                    else [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": "Your previous response was invalid JSON. Return ONLY valid raw JSON matching the schema (no markdown).",
                        },
                    ]
                ),
                temperature=0.2 if attempt == 0 else 0.0,
                max_tokens=1200,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                last_err = ValueError("empty response")
                continue
            try:
                parsed = self._parse_planner_json(raw)
                if isinstance(parsed, dict):
                    payload = parsed
                    break
                last_err = ValueError("response was not a JSON object")
            except Exception as e:
                last_err = e
                continue

        if payload is None and not self.config.best_effort:
            detail = f": {last_err}" if last_err else ""
            raise SynthesisError(f"Synthesis returned invalid JSON{detail}", raw=raw, stage="synthesize")

        if payload is not None:
            payload = self._repair_and_validate_synthesis_payload(
                query=query,
                findings=findings,
                allowed_urls=set(citations),
                payload=payload,
            )

        md = self._render_from_payload(query=query, findings=findings, citations=citations, payload=(payload or {}))
        return md, payload

    def _repair_and_validate_synthesis_payload(
        self,
        *,
        query: str,
        findings: list[dict[str, Any]],
        allowed_urls: set[str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        issues = self._synthesis_payload_grounding_issues(payload, allowed_urls=allowed_urls)
        coverage_issues, stats = self._synthesis_payload_coverage_issues(
            payload,
            allowed_urls=allowed_urls,
            min_unique_citations_target=max(0, int(self.config.report_min_unique_citations_target)),
            min_unique_domains_target=max(0, int(self.config.report_min_unique_domains_target)),
            findings_target=max(1, int(self.config.report_findings_target)),
        )

        # Hard-fix grounding issues; best-effort only applies to coverage.
        if issues or coverage_issues:
            repaired = self._attempt_synthesis_repair(
                query=query,
                findings=findings,
                allowed_urls=sorted(allowed_urls),
                payload=payload,
                issues=issues + coverage_issues,
            )
            if repaired is not None:
                payload = repaired
                issues = self._synthesis_payload_grounding_issues(payload, allowed_urls=allowed_urls)
                coverage_issues, stats = self._synthesis_payload_coverage_issues(
                    payload,
                    allowed_urls=allowed_urls,
                    min_unique_citations_target=max(0, int(self.config.report_min_unique_citations_target)),
                    min_unique_domains_target=max(0, int(self.config.report_min_unique_domains_target)),
                    findings_target=max(1, int(self.config.report_findings_target)),
                )

        if issues:
            raise SynthesisError(
                "Synthesis produced citations not present in allowed sources",
                raw=json.dumps(payload, ensure_ascii=False),
                stage="synthesize",
            )

        if coverage_issues:
            msg = (
                "Synthesis did not meet coverage targets. "
                + ", ".join(coverage_issues[:3])
                + f" (unique_citations={stats.get('unique_citations')}, domains={stats.get('unique_domains')}, target_per_finding={stats.get('target_per_finding')})"
            )
            if str(self.config.coverage_mode or "warn").lower() == "error":
                raise SynthesisError(msg, raw=json.dumps(payload, ensure_ascii=False), stage="coverage")
            if self.emitter is not None:
                self.emitter.emit(ProgressEvent(stage="synthesize", current=0, total=None, message=f"WARNING: {msg}"))

        return payload

    def _attempt_synthesis_repair(
        self,
        *,
        query: str,
        findings: list[dict[str, Any]],
        allowed_urls: list[str],
        payload: dict[str, Any],
        issues: list[str],
    ) -> dict[str, Any] | None:
        if not issues:
            return None
        prompt = self._synthesis_prompt_with_constraints(query, findings, allowed_urls=allowed_urls)
        allowed_block = _allowed_sources_block(allowed_urls, max_items=60)
        msg = (
            "Your previous JSON did not meet requirements.\n\n"
            "Problems:\n"
            + "\n".join(f"- {i}" for i in issues[:12])
            + ("\n\n" + allowed_block if allowed_block else "")
            + "\n\nReturn ONLY corrected raw JSON matching the schema (no markdown). "
            + "Cite ONLY from the Allowed citation URLs list."
        )
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": msg},
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        raw = (resp.choices[0].message.content or "").strip()
        try:
            parsed = self._parse_planner_json(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

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

    def _synthesis_payload_coverage_issues(
        self,
        payload: dict[str, Any],
        *,
        allowed_urls: set[str],
        min_unique_citations_target: int,
        min_unique_domains_target: int,
        findings_target: int,
    ) -> tuple[list[str], dict[str, Any]]:
        urls: set[str] = set()
        per_finding_counts: list[int] = []
        findings = payload.get("findings")
        if isinstance(findings, list):
            for it in findings:
                if not isinstance(it, dict):
                    continue
                cites = it.get("citations") or []
                if not isinstance(cites, list):
                    continue
                kept = 0
                for c in cites:
                    if isinstance(c, str) and c in allowed_urls:
                        urls.add(c)
                        kept += 1
                per_finding_counts.append(kept)
        domains = {urlparse(u).netloc for u in urls}
        issues: list[str] = []
        if min_unique_citations_target and len(urls) < min_unique_citations_target:
            issues.append(
                f"unique citations below target: {len(urls)} < {min_unique_citations_target}"
            )
        if min_unique_domains_target and len(domains) < min_unique_domains_target:
            issues.append(
                f"unique domains below target: {len(domains)} < {min_unique_domains_target}"
            )
        effective_findings = max(1, min(int(findings_target), len(per_finding_counts) or int(findings_target)))
        target_per_finding = 2 if len(allowed_urls) >= effective_findings * 2 else 1
        if per_finding_counts:
            below = sum(1 for n in per_finding_counts[:effective_findings] if n < target_per_finding)
            if below:
                issues.append(f"{below} finding(s) below per-finding citation target: {target_per_finding}")
        return issues, {
            "unique_citations": len(urls),
            "unique_domains": len(domains),
            "target_per_finding": target_per_finding,
        }

