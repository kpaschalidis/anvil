from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from anvil.subagents.parallel import WorkerResult
from anvil.workflows.iterative_loop import (
    CatalogCandidate,
    CatalogMemo,
    FieldStatus,
    Gap,
    ReportType,
    ResearchMemo,
    SourceEntry,
    detect_required_fields,
    detect_target_items,
)


class DeepResearchMemoMixin:
    def _build_round_memo(
        self,
        *,
        query: str,
        report_type: ReportType,
        round_index: int,
        tasks_completed: int,
        tasks_remaining: int,
        findings: list[dict[str, Any]],
    ) -> ResearchMemo:
        urls: set[str] = set()
        evidence_urls: set[str] = set()
        sources: dict[str, dict[str, str]] = {}
        pages_extracted = 0

        for f in findings:
            if not isinstance(f, dict):
                continue
            cits = f.get("citations")
            if isinstance(cits, list):
                for u in cits:
                    if isinstance(u, str) and u.startswith("http"):
                        urls.add(u)
            srcs = f.get("sources")
            if isinstance(srcs, dict):
                for u, meta in srcs.items():
                    if isinstance(u, str) and u.startswith("http") and isinstance(meta, dict):
                        sources[u] = {k: str(v) for k, v in meta.items() if isinstance(k, str)}
            evs = f.get("evidence")
            if isinstance(evs, list):
                for ev in evs:
                    if not isinstance(ev, dict):
                        continue
                    u = ev.get("url")
                    if isinstance(u, str) and u.startswith("http"):
                        evidence_urls.add(u)
                pages_extracted += len(
                    [ev for ev in evs if isinstance(ev, dict) and isinstance(ev.get("url"), str)]
                )

        domains = {urlparse(u).netloc.lower().strip() for u in urls if isinstance(u, str) and u.startswith("http")}

        def _relevance(u: str) -> str:
            path = urlparse(u).path.lower()
            if any(k in path for k in ("/pricing", "pricing", "plans", "case-study", "case-studies", "customer")):
                return "pricing"
            if any(k in path for k in ("/docs", "/spec", "/reference", "/api", "/security")):
                return "reference"
            return "overview"

        sources_summary: list[SourceEntry] = []
        per_domain: dict[str, int] = {}
        ordered_urls = list(evidence_urls) + [u for u in urls if u not in evidence_urls]
        for u in ordered_urls:
            if not isinstance(u, str) or not u.startswith("http"):
                continue
            d = urlparse(u).netloc.lower().strip()
            if not d:
                continue
            if per_domain.get(d, 0) >= 3:
                continue
            meta = sources.get(u, {})
            sources_summary.append(
                SourceEntry(
                    url=u,
                    domain=d,
                    title=str(meta.get("title") or ""),
                    has_evidence=u in evidence_urls,
                    relevance=_relevance(u),
                )
            )
            per_domain[d] = per_domain.get(d, 0) + 1
            if len(sources_summary) >= 20:
                break

        base_kwargs = {
            "query": query,
            "report_type": report_type,
            "round_index": int(round_index),
            "tasks_completed": int(tasks_completed),
            "tasks_remaining": int(tasks_remaining),
            "unique_citations": len(urls),
            "unique_domains": len({d for d in domains if d}),
            "pages_extracted": int(pages_extracted),
            "themes_covered": (),
            "sources_summary": tuple(sources_summary),
        }

        if report_type == ReportType.CATALOG:
            target_items = detect_target_items(query) or 5
            required_fields_raw = detect_required_fields(query)
            required_fields = self._normalize_catalog_required_fields(required_fields_raw)
            candidates = self._extract_catalog_candidates(findings, required_fields=required_fields)
            gaps = self._catalog_gaps(candidates=candidates, target_items=target_items)
            return CatalogMemo(
                **base_kwargs,
                gaps=tuple(gaps),
                claims_to_verify=(),
                target_items=int(target_items),
                candidates=tuple(candidates),
                required_fields=tuple(required_fields),
            )

        gaps: list[Gap] = []
        # Narrative gaps: deterministic coverage/evidence gaps only (no subjective tiering).
        min_domains_target = max(
            0,
            int(self.config.min_total_domains),
            int(self.config.report_min_unique_domains_target),
        )
        min_citations_target = max(
            0,
            int(self.config.min_total_citations),
            int(self.config.report_min_unique_citations_target),
        )

        unique_domains = len({d for d in domains if d})
        unique_citations = len(urls)

        if min_domains_target and unique_domains < min_domains_target:
            gaps.append(
                Gap(
                    gap_type="coverage_domains",
                    description=f"Need more unique domains: {unique_domains} < {min_domains_target}",
                    priority=1,
                    suggested_query=f"{query} official docs specification reference",
                )
            )

        if min_citations_target and unique_citations < min_citations_target:
            gaps.append(
                Gap(
                    gap_type="coverage_citations",
                    description=f"Need more unique citations: {unique_citations} < {min_citations_target}",
                    priority=2,
                    suggested_query=f"{query} overview guide examples",
                )
            )

        if bool(self.config.enable_deep_read) and bool(self.config.require_quote_per_claim):
            if int(pages_extracted) <= 0:
                gaps.append(
                    Gap(
                        gap_type="missing_evidence",
                        description="Need extracted page evidence (quotes) for grounded claims",
                        priority=1,
                        suggested_query=f"{query} documentation",
                    )
                )

        return ResearchMemo(
            **base_kwargs,
            gaps=tuple(gaps[:10]),
            claims_to_verify=(),
        )

    def _normalize_catalog_required_fields(self, raw_fields: list[str]) -> tuple[str, ...]:
        """
        Normalize user-provided field labels into canonical catalog keys.

        Canonical keys are the ones the worker contract returns (and the synthesizer expects).
        """
        canonical: list[str] = []

        def add(key: str) -> None:
            if key not in canonical:
                canonical.append(key)

        for f in raw_fields or []:
            s = str(f).strip().lower()
            if not s:
                continue
            if "url" in s or ("website" in s and "provider" in s):
                add("website_url")
            elif "pricing" in s or "price" in s or "retainer" in s or "contract" in s:
                add("pricing_model")
            elif "case" in s or "testimonial" in s or "proof" in s:
                add("proof_links")
            elif "problem" in s:
                add("problem_solved")
            elif "for whom" in s or "who" in s or "customer" in s:
                add("who_its_for")
            elif "automation" in s or "ai" in s:
                add("how_ai_is_used")
            elif "evergreen" in s:
                add("why_evergreen")
            elif "replic" in s or "tools" in s:
                add("replicable_with")
            elif "name" in s or "provider" in s or "company" in s:
                add("name")

        # Always require the essentials for a usable catalog.
        add("name")
        add("website_url")
        add("problem_solved")
        add("pricing_model")
        add("proof_links")
        return tuple(canonical[:30])

    def _extract_catalog_candidates(
        self,
        findings: list[dict[str, Any]],
        *,
        required_fields: tuple[str, ...],
    ) -> list[CatalogCandidate]:
        """
        Parse worker outputs for catalog-style runs.

        Workers are expected to return JSON with a top-level `candidates` array.
        """
        out: list[CatalogCandidate] = []
        seen: set[str] = set()

        for f in findings:
            if not isinstance(f, dict):
                continue
            raw = str(f.get("output") or "").strip()
            if not raw:
                continue
            try:
                payload = self._parse_planner_json(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            items = payload.get("candidates")
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or it.get("provider") or it.get("company") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                provider_url = str(it.get("website_url") or it.get("provider_url") or it.get("url") or "").strip() or None

                fields: dict[str, FieldStatus] = {}
                for rf in required_fields:
                    v = it.get(rf)
                    if rf == "website_url":
                        v = provider_url
                    if rf == "proof_links":
                        v = it.get("proof_links")
                    if rf == "pricing_model":
                        v = it.get("pricing_model")

                    if isinstance(v, str):
                        fields[rf] = FieldStatus.FOUND if v.strip() else FieldStatus.MISSING
                    elif isinstance(v, list):
                        fields[rf] = (
                            FieldStatus.FOUND if any(isinstance(x, str) and x.strip() for x in v) else FieldStatus.MISSING
                        )
                    else:
                        fields[rf] = FieldStatus.MISSING

                out.append(
                    CatalogCandidate(
                        name=name,
                        provider_url=provider_url,
                        fields=fields,
                        evidence_urls=(),
                    )
                )

        return out

    def _catalog_gaps(self, *, candidates: list[CatalogCandidate], target_items: int) -> list[Gap]:
        gaps: list[Gap] = []
        want = max(1, int(target_items)) * 2
        if len(candidates) < want:
            gaps.append(
                Gap(
                    gap_type="missing_candidates",
                    description=f"Need more candidates: have {len(candidates)}, want {want}",
                    priority=1,
                    suggested_query="AI service provider pricing case study",
                )
            )

        for c in candidates:
            missing = [k for k, v in (c.fields or {}).items() if v == FieldStatus.MISSING]
            if not missing:
                continue
            priority = 1 if any("pricing" in m for m in missing) else 2
            suggested = None
            if any("pricing" in m for m in missing):
                suggested = f"\"{c.name}\" pricing cost plans"
            elif any("proof" in m or "case" in m for m in missing):
                suggested = f"\"{c.name}\" case study customer testimonial"
            else:
                suggested = f"\"{c.name}\" {' '.join(missing)}"
            gaps.append(
                Gap(
                    gap_type="missing_field",
                    description=f"{c.name}: missing {', '.join(missing)}",
                    priority=priority,
                    candidate_name=c.name,
                    missing_fields=tuple(missing),
                    suggested_query=suggested,
                )
            )

        gaps.sort(key=lambda g: int(getattr(g, "priority", 2) or 2))
        return gaps[:10]

    def _findings_from_results(self, results: list[WorkerResult]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in results:
            out.append(
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "citations": list(r.citations),
                    "sources": getattr(r, "sources", {}) or {},
                    "evidence": list(getattr(r, "evidence", ()) or ()),
                    "web_search_calls": int(r.web_search_calls or 0),
                    "web_extract_calls": int(getattr(r, "web_extract_calls", 0) or 0),
                }
            )
        return out

