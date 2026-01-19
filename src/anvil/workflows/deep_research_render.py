from __future__ import annotations

from typing import Any

from anvil.workflows.deep_research_types import sanitize_snippet


class DeepResearchRenderMixin:
    def _render_catalog_payload(
        self,
        *,
        payload: dict[str, Any],
        citations: list[str],
        evidence: list[dict[str, Any]],
    ) -> str:
        title = str(payload.get("title") or "Catalog Report")
        summary = payload.get("summary_bullets") or []
        items = payload.get("items") or []
        open_qs = payload.get("open_questions") or []

        allowed = set(citations)
        evidence_map = {
            str(it.get("url")): it
            for it in evidence
            if isinstance(it, dict) and isinstance(it.get("url"), str)
        }

        citation_numbers: dict[str, int] = {}
        ordered_urls: list[str] = []

        def _num(url: str) -> int:
            if url not in citation_numbers:
                citation_numbers[url] = len(citation_numbers) + 1
                ordered_urls.append(url)
            return citation_numbers[url]

        def _norm(s: str) -> str:
            return " ".join((s or "").split())

        lines: list[str] = [f"# {title}", ""]
        if isinstance(summary, list) and summary:
            lines.append("## Summary")
            for b in summary[:12]:
                if isinstance(b, str) and b.strip():
                    lines.append(f"- {b.strip()}")
            lines.append("")

        if isinstance(items, list) and items:
            lines.append("## Service Models")
            for idx, it in enumerate(items, start=1):
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or "").strip() or f"Item {idx}"
                provider = str(it.get("provider") or "").strip()
                header = f"### {idx}. {name}" + (f" — {provider}" if provider else "")
                lines.append(header)

                website_url = it.get("website_url")
                if isinstance(website_url, str) and website_url in allowed:
                    n = _num(website_url)
                    lines.append(f"- Website: [{n}]({website_url}) {website_url}")

                def add_line(label: str, key: str) -> None:
                    v = str(it.get(key) or "").strip()
                    if v:
                        lines.append(f"- {label}: {v}")

                add_line("Problem", "problem_solved")
                add_line("For", "who_its_for")
                add_line("How AI is used", "how_ai_is_used")
                add_line("Pricing", "pricing_model")
                add_line("Evergreen", "why_evergreen")
                add_line("Replicable with", "replicable_with")

                proof_links = it.get("proof_links") or []
                proof_links = [u for u in proof_links if isinstance(u, str) and u in allowed]
                if proof_links:
                    rendered = ", ".join(f"[{_num(u)}]({u})" for u in proof_links[:3])
                    lines.append(f"- Proof: {rendered}")

                ev = it.get("evidence") or []
                if isinstance(ev, list) and ev:
                    kept = []
                    for e in ev:
                        if not isinstance(e, dict):
                            continue
                        url = e.get("url")
                        quote = e.get("quote")
                        if isinstance(url, str) and url in allowed and isinstance(quote, str) and url in evidence_map:
                            kept.append((url, quote))
                        if len(kept) >= 2:
                            break
                    for url, quote in kept:
                        n = _num(url)
                        lines.append(f"- Quote: “{_norm(quote)}” [{n}]({url})")
                lines.append("")

        if isinstance(open_qs, list) and open_qs:
            lines.append("## Open Questions")
            for q in open_qs[:12]:
                if isinstance(q, str) and q.strip():
                    lines.append(f"- {q.strip()}")
            lines.append("")

        if ordered_urls:
            lines.append("## Sources")
            for u in ordered_urls:
                n = citation_numbers[u]
                meta = evidence_map.get(u) or {}
                t = str(meta.get("title") or "").strip()
                label = f"{t} — {u}" if t else u
                lines.append(f"- [{n}]({u}) {label}")
            lines.append("")

        return "\n".join(lines).strip()

    def _render_from_payload(
        self,
        *,
        query: str,
        findings: list[dict[str, Any]],
        citations: list[str],
        payload: dict[str, Any],
    ) -> str:
        title = str(payload.get("title") or "Deep Research Report")
        summary = payload.get("summary_bullets") or []
        findings_out = payload.get("findings") or []
        open_qs = payload.get("open_questions") or []

        allowed = set(citations)
        source_meta: dict[str, dict[str, str]] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            m = f.get("sources")
            if isinstance(m, dict):
                for url, meta in m.items():
                    if isinstance(url, str) and url.startswith("http") and isinstance(meta, dict):
                        merged: dict[str, str] = {}
                        t = meta.get("title")
                        snippet = meta.get("snippet")
                        if isinstance(t, str) and t.strip():
                            merged["title"] = t.strip()
                        if isinstance(snippet, str) and snippet.strip():
                            merged["snippet"] = sanitize_snippet(snippet)
                        if merged:
                            source_meta.setdefault(url, {}).update(merged)
            ev = f.get("evidence")
            if isinstance(ev, list):
                for item in ev:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    if not (isinstance(url, str) and url.startswith("http")):
                        continue
                    merged: dict[str, str] = {}
                    t = item.get("title")
                    excerpt = item.get("excerpt")
                    if isinstance(t, str) and t.strip():
                        merged["title"] = t.strip()
                    if isinstance(excerpt, str) and excerpt.strip():
                        merged["excerpt"] = excerpt.strip()
                    if merged:
                        source_meta.setdefault(url, {}).update(merged)

        evidence_text: dict[str, str] = {}
        if self.config.require_quote_per_claim:
            for url, meta in source_meta.items():
                ex = meta.get("excerpt")
                if isinstance(ex, str) and ex.strip():
                    evidence_text[url] = ex

        citation_numbers: dict[str, int] = {}
        ordered_urls: list[str] = []

        def _num(url: str) -> int:
            if url not in citation_numbers:
                citation_numbers[url] = len(citation_numbers) + 1
                ordered_urls.append(url)
            return citation_numbers[url]

        def _why(url: str) -> str:
            meta = source_meta.get(url) or {}
            snippet = (meta.get("excerpt") or meta.get("snippet") or "").strip()
            t = (meta.get("title") or "").strip()
            if snippet:
                s = " ".join(snippet.split())
                return s[:220] + ("…" if len(s) > 220 else "")
            if t:
                return t
            return url.split("/")[2] if url.startswith("http") else url

        def _norm(s: str) -> str:
            return " ".join((s or "").split())

        def _quote_ok(url: str, quote: str) -> bool:
            q = _norm(quote)
            if not q:
                return False
            txt = _norm(evidence_text.get(url, ""))
            return q in txt

        rendered_findings: list[str] = []
        if isinstance(findings_out, list):
            for it in findings_out:
                if not isinstance(it, dict):
                    continue
                claim = str(it.get("claim") or "").strip()
                if not claim:
                    continue
                if self.config.require_quote_per_claim:
                    ev = it.get("evidence") or []
                    if not isinstance(ev, list):
                        ev = []
                    ev_items = []
                    for e in ev:
                        if not isinstance(e, dict):
                            continue
                        url = e.get("url")
                        quote = e.get("quote")
                        if not (isinstance(url, str) and url in allowed and isinstance(quote, str)):
                            continue
                        if not _quote_ok(url, quote):
                            continue
                        ev_items.append({"url": url, "quote": quote.strip()})
                    if not ev_items:
                        if self.config.best_effort:
                            continue
                        raise RuntimeError(f"Synthesis produced an unsupported claim: {claim}")
                    urls = [x["url"] for x in ev_items]
                    nums = [_num(u) for u in urls]
                    links = "".join(f"[{n}]" for n in nums[:3])
                    primary = ev_items[0]
                    rendered_findings.append(f"- {claim} {links}")
                    rendered_findings.append(f"  - Why: {_why(primary['url'])}")
                    rendered_findings.append(f"  - Quote: “{_norm(primary['quote'])}”")
                else:
                    cites = it.get("citations") or []
                    if not isinstance(cites, list):
                        cites = []
                    cites = [c for c in cites if isinstance(c, str) and c in allowed]
                    if not cites:
                        if self.config.best_effort:
                            continue
                        raise RuntimeError(f"Synthesis produced an uncited claim: {claim}")
                    nums = [_num(u) for u in cites]
                    links = "".join(f"[{n}]" for n in nums[:3])
                    primary = cites[0]
                    rendered_findings.append(f"- {claim} {links}")
                    rendered_findings.append(f"  - Why: {_why(primary)}")

        lines: list[str] = [f"# {title}", ""]
        if isinstance(summary, list) and summary:
            lines.append("## Summary")
            for b in summary[:12]:
                if isinstance(b, str) and b.strip():
                    lines.append(f"- {b.strip()}")
            lines.append("")

        if rendered_findings:
            lines.append("## Findings")
            lines.extend(rendered_findings)
            lines.append("")

        if isinstance(open_qs, list) and open_qs:
            lines.append("## Open Questions")
            for q in open_qs[:12]:
                if isinstance(q, str) and q.strip():
                    lines.append(f"- {q.strip()}")
            lines.append("")

        if ordered_urls:
            lines.append("## Sources")
            for u in ordered_urls:
                n = citation_numbers[u]
                meta = source_meta.get(u) or {}
                t = (meta.get("title") or "").strip()
                label = f"{t} — {u}" if t else u
                lines.append(f"- [{n}]({u}) {label}")
            lines.append("")

        return "\n".join(lines).strip()

