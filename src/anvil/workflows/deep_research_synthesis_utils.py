from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def _compact_findings_for_outline(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Reduce worker findings to a small, outline-friendly payload.

    The outline stage only needs task IDs + a short gist; it does not need full excerpts,
    full citation lists, or large markdown outputs (these can exceed context windows).
    """
    out: list[dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        task_id = str(f.get("task_id") or "").strip()
        if not task_id:
            continue
        output = str(f.get("output") or "")
        if len(output) > 800:
            output = output[:800].rstrip() + "…"
        urls = f.get("citations")
        urls_list = [u for u in urls if isinstance(u, str) and u.startswith("http")] if isinstance(urls, list) else []
        out.append(
            {
                "task_id": task_id,
                "success": bool(f.get("success", True)),
                "citations_count": len(urls_list),
                "top_urls": urls_list[:6],
                "note": output,
            }
        )
    return out


def _select_diverse_findings(
    candidates: list[dict[str, Any]],
    *,
    target_findings: int,
    min_unique_urls_target: int,
    min_unique_domains_target: int,
) -> list[dict[str, Any]]:
    """
    Deterministically select findings to maximize unique evidence URLs/domains.

    This helps deep mode translate large evidence collection into a diverse report without
    adding extra LLM passes.
    """
    target_findings = max(0, int(target_findings))
    if target_findings <= 0:
        return candidates

    def urls_for(it: dict[str, Any]) -> list[str]:
        ev = it.get("evidence") or []
        if not isinstance(ev, list):
            return []
        out = []
        for e in ev:
            if not isinstance(e, dict):
                continue
            u = e.get("url")
            if isinstance(u, str) and u.startswith("http"):
                out.append(u)
        return out

    def domains_for(urls: list[str]) -> set[str]:
        ds: set[str] = set()
        for u in urls:
            try:
                netloc = urlparse(u).netloc.lower().strip()
            except Exception:
                continue
            if netloc:
                ds.add(netloc)
        return ds

    remaining = [it for it in candidates if isinstance(it, dict)]
    selected: list[dict[str, Any]] = []
    used_urls: set[str] = set()
    used_domains: set[str] = set()

    # Greedy set cover: repeatedly pick the finding that adds the most new URLs/domains.
    while remaining and len(selected) < target_findings:
        best_idx = None
        best_score = None
        best_reordered = None

        for idx, it in enumerate(remaining):
            u = urls_for(it)
            if not u:
                continue
            d = domains_for(u)
            new_u = [x for x in u if x not in used_urls]
            new_d = [x for x in d if x not in used_domains]

            # Prefer 2+ evidence items for deep mode diversity.
            evidence_count = len(u)

            # Score: new URLs dominate, then new domains, then evidence count.
            score = (len(new_u) * 100) + (len(new_d) * 10) + (min(evidence_count, 3))

            # Also reorder evidence so the first URL is unused if possible.
            ev = it.get("evidence") or []
            if isinstance(ev, list) and ev:
                ev_kept = [e for e in ev if isinstance(e, dict) and isinstance(e.get("url"), str)]
                if ev_kept:
                    ev_kept.sort(key=lambda e: 0 if e.get("url") in used_urls else -1)
                    it2 = dict(it)
                    it2["evidence"] = ev_kept[:3]
                else:
                    it2 = it
            else:
                it2 = it

            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx
                best_reordered = it2

        if best_idx is None or best_reordered is None:
            break

        picked = remaining.pop(best_idx)
        # Use reordered evidence if we built it.
        if best_reordered is not picked:
            picked = best_reordered
        selected.append(picked)

        u = urls_for(picked)
        used_urls.update(u)
        used_domains.update(domains_for(u))

    # If we still don't meet diversity targets, keep adding remaining findings to fill count.
    # (We still preserve grounding; coverage failures are handled by config elsewhere.)
    while remaining and len(selected) < target_findings:
        selected.append(remaining.pop(0))

    # Trim any findings list fields that might have grown too large.
    out: list[dict[str, Any]] = []
    for it in selected:
        if not isinstance(it, dict):
            continue
        ev = it.get("evidence") or []
        if isinstance(ev, list):
            it = dict(it)
            it["evidence"] = [e for e in ev if isinstance(e, dict)][:3]
        out.append(it)

    # Diversity targets are hints; enforce count only here.
    _ = (min_unique_urls_target, min_unique_domains_target)
    return out

