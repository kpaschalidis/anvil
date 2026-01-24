from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from common import llm
from common.events import EventEmitter, ProgressEvent, ResearchPlanEvent

from anvil.subagents.parallel import ParallelWorkerRunner, WorkerResult, WorkerTask
from anvil.subagents.task_tool import SubagentRunner
from anvil.workflows.deep_research_planning import DeepResearchPlanningMixin
from anvil.workflows.deep_research_render import DeepResearchRenderMixin
from anvil.workflows.deep_research_synthesis import DeepResearchSynthesisMixin
from anvil.workflows.deep_research_types import (
    DeepResearchConfig,
    DeepResearchOutcome,
    DeepResearchRunError,
    PlanningError,
    ReportType,
    SynthesisError,
    detect_report_type,
    sanitize_snippet,
)
from anvil.workflows.deep_research_utils import select_top_findings
from anvil.workflows.deep_research_workers import DeepResearchWorkersMixin


class DeepResearchWorkflow(
    DeepResearchPlanningMixin,
    DeepResearchWorkersMixin,
    DeepResearchRenderMixin,
    DeepResearchSynthesisMixin,
):
    """Draft-centric deep research loop (v3)."""

    def __init__(
        self,
        *,
        subagent_runner: SubagentRunner,
        parallel_runner: ParallelWorkerRunner,
        config: DeepResearchConfig,
        emitter: EventEmitter | None = None,
    ):
        self.subagent_runner = subagent_runner
        self.parallel_runner = parallel_runner
        self.config = config
        self.emitter = emitter

    def run(self, query: str) -> DeepResearchOutcome:
        query = (query or "").strip()
        if not query:
            raise ValueError("query is required")

        report_type = detect_report_type(query)

        max_tasks_total = max(1, int(self.config.max_tasks_total))
        max_tasks_per_round = max(1, int(self.config.max_tasks_per_round))

        max_iterations = int(getattr(self.config, "max_iterations", 0) or 0)
        if max_iterations <= 0:
            max_iterations = max(1, int(self.config.max_rounds))

        saturation_threshold = max(0, int(getattr(self.config, "saturation_threshold", 0) or 0))
        if saturation_threshold <= 0:
            saturation_threshold = 2

        if report_type == ReportType.CATALOG:
            max_tasks_total = max(max_tasks_total, 15)

        planner_raw = ""
        planner_error: str | None = None

        draft = ""
        seen_queries: set[str] = set()
        all_findings: list[dict[str, Any]] = []
        all_results: list[WorkerResult] = []
        all_tasks: list[WorkerTask] = []
        all_citations: set[str] = set()
        all_domains: set[str] = set()
        rounds: list[dict[str, Any]] = []
        plans: list[dict[str, Any]] = []

        stop_reason = "max_iterations"

        def _norm_query(s: str) -> str:
            return " ".join((s or "").strip().lower().split())

        for iteration in range(max_iterations):
            remaining_total = max(0, max_tasks_total - len(all_tasks))
            budget = min(max_tasks_per_round, remaining_total)
            if budget <= 0:
                stop_reason = "task_budget_exhausted"
                break

            if iteration == 0:
                if self.emitter is not None:
                    self.emitter.emit(ProgressEvent(stage="plan", current=0, total=None, message="Planning searches"))
                plan, planner_raw, planner_error = self._plan(
                    query,
                    max_tasks=budget,
                    min_tasks=min(3, budget),
                    report_type=report_type,
                )
            else:
                if self.emitter is not None:
                    self.emitter.emit(
                        ProgressEvent(stage="gap", current=0, total=None, message="Planning follow-up searches")
                    )
                plan, raw, err = self._plan_continuation(
                    query=query,
                    draft=draft,
                    seen_queries=seen_queries,
                    max_tasks=budget,
                )
                if err and not self.config.best_effort:
                    raise PlanningError(err, raw=raw)
                rounds.append(
                    {
                        "round_index": iteration + 1,
                        "stage": "plan",
                        "plan": plan,
                        "planner_raw": raw,
                        "planner_error": err,
                        "task_ids": [],
                    }
                )

            plans.append(plan)

            tasks_list = plan.get("tasks") if isinstance(plan, dict) else None
            planned: list[dict[str, Any]] = []
            planned_queries: list[str] = []
            if isinstance(tasks_list, list):
                for t in tasks_list:
                    if not isinstance(t, dict):
                        continue
                    planned.append(
                        {
                            "id": t.get("id"),
                            "search_query": t.get("search_query"),
                            "instructions": t.get("instructions"),
                        }
                    )
                    q = t.get("search_query")
                    if isinstance(q, str) and q.strip():
                        planned_queries.append(_norm_query(q))

            novel = [q for q in planned_queries if q and q not in seen_queries]
            if not novel and iteration > 0:
                stop_reason = "no_novel_queries"
                break
            for q in novel:
                seen_queries.add(q)

            if self.emitter is not None and planned:
                self.emitter.emit(ResearchPlanEvent(tasks=planned))

            round_tasks = self._to_worker_tasks(query, plan)[:budget]
            if not round_tasks:
                stop_reason = "no_tasks"
                break

            all_tasks.extend(round_tasks)

            results = self._run_round(
                stage_label="workers",
                message=f"Running {len(round_tasks)} tasks (max concurrency: {self.config.max_workers})",
                tasks=round_tasks,
            )
            all_results.extend(results)

            findings = self._findings_from_results(results)
            all_findings.extend(findings)

            iter_citations = set(self._collect_citations_from_traces(results))
            new_citations = {u for u in iter_citations if u not in all_citations}
            new_domains = set(self._collect_domains(sorted(new_citations))) - all_domains

            rounds.append(
                {
                    "round_index": iteration + 1,
                    "stage": "iteration",
                    "plan": plan,
                    "planner_raw": planner_raw if iteration == 0 else "",
                    "planner_error": planner_error if iteration == 0 else None,
                    "task_ids": [t.id for t in round_tasks],
                    "new_citations": len(new_citations),
                    "new_domains": len(new_domains),
                }
            )

            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(
                        stage="round",
                        current=iteration + 1,
                        total=max_iterations,
                        message=(
                            f"Iteration {iteration + 1} complete: tasks={len(all_tasks)} "
                            f"new_citations={len(new_citations)} new_domains={len(new_domains)}"
                        ),
                    )
                )

            if iteration > 0 and len(new_domains) == 0 and len(new_citations) < saturation_threshold:
                stop_reason = "saturated"
                break

            all_citations.update(new_citations)
            all_domains.update(new_domains)

            top_findings = select_top_findings(findings, k=10)
            draft = self._refine_draft(query=query, report_type=report_type, draft=draft, findings=top_findings)

        citations = (
            self._collect_evidence_urls(all_results)
            if self.config.enable_deep_read
            else self._collect_citations_from_traces(all_results)
        )
        domains = self._collect_domains(citations)

        failures = [r for r in all_results if not r.success]
        if self.config.strict_all and failures and not self.config.best_effort:
            raise RuntimeError(
                "Deep research failed because one or more workers failed.\n\n"
                f"Diagnostics:\n{self._format_worker_diagnostics(all_results)}"
            )

        if self.config.require_citations and not self.config.best_effort:
            if len(citations) < self.config.min_total_citations:
                raise RuntimeError(
                    "Deep research requires web citations but none (or too few) were collected.\n"
                    "Fix: run `uv sync --extra search` and ensure `TAVILY_API_KEY` is set.\n\n"
                    f"Diagnostics:\n{self._format_worker_diagnostics(all_results)}"
                )
            if len(domains) < max(0, int(self.config.min_total_domains)):
                raise RuntimeError(
                    "Deep research requires broader source coverage but too few unique domains were collected.\n"
                    f"Need >= {self.config.min_total_domains} domains, got {len(domains)}.\n\n"
                    f"Diagnostics:\n{self._format_worker_diagnostics(all_results)}"
                )

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="synthesize", current=0, total=None, message="Synthesizing report"))

        curated_sources: list[dict[str, Any]] | None = None
        synthesis_findings = all_findings
        synthesis_allowed_urls = list(citations)
        if not self.config.require_quote_per_claim and int(self.config.curated_sources_max_total) > 0:
            curated_sources = self._build_curated_sources(
                results=all_results,
                max_total=int(self.config.curated_sources_max_total),
                max_per_domain=int(self.config.curated_sources_max_per_domain),
                min_per_task=int(self.config.curated_sources_min_per_task),
            )
            curated_urls = {
                str(s.get("url"))
                for s in curated_sources
                if isinstance(s, dict) and isinstance(s.get("url"), str) and str(s.get("url")) in set(citations)
            }
            synthesis_allowed_urls = sorted(curated_urls)
            if not synthesis_allowed_urls:
                curated_sources = None
                synthesis_allowed_urls = list(citations)
                synthesis_findings = all_findings
            else:
                synthesis_findings = self._build_synthesis_findings(
                    results=all_results,
                    allowed_urls=set(synthesis_allowed_urls),
                )

        synthesis_input = self._build_synthesis_input(
            query=query,
            findings=synthesis_findings,
            allowed_urls=sorted(set(citations)),
            curated_sources=curated_sources,
        )

        try:
            report, report_json = self._synthesize_and_render(
                query,
                synthesis_findings,
                synthesis_allowed_urls,
                report_type=report_type,
            )
        except SynthesisError as e:
            combined_plan = {"tasks": []}
            tasks_out: list[dict[str, Any]] = []
            for p in plans:
                if not isinstance(p, dict):
                    continue
                for t in p.get("tasks") or []:
                    if isinstance(t, dict):
                        tasks_out.append(t)
            if tasks_out:
                combined_plan["tasks"] = tasks_out
            raise DeepResearchRunError(
                str(e),
                outcome=DeepResearchOutcome(
                    query=query,
                    plan=combined_plan,
                    planner_raw=planner_raw,
                    planner_error=planner_error,
                    tasks=all_tasks,
                    results=all_results,
                    citations=citations,
                    report_markdown="",
                    report_json=None,
                    rounds=rounds,
                    synthesis_stage=e.stage,
                    synthesis_raw=e.raw,
                    synthesis_error=str(e),
                    synthesis_input=synthesis_input,
                    curated_sources=curated_sources,
                ),
            ) from e
        except Exception as e:
            se = SynthesisError(str(e), stage="synthesize")
            combined_plan = {"tasks": []}
            tasks_out = []
            for p in plans:
                if not isinstance(p, dict):
                    continue
                for t in p.get("tasks") or []:
                    if isinstance(t, dict):
                        tasks_out.append(t)
            if tasks_out:
                combined_plan["tasks"] = tasks_out
            raise DeepResearchRunError(
                str(se),
                outcome=DeepResearchOutcome(
                    query=query,
                    plan=combined_plan,
                    planner_raw=planner_raw,
                    planner_error=planner_error,
                    tasks=all_tasks,
                    results=all_results,
                    citations=citations,
                    report_markdown="",
                    report_json=None,
                    rounds=rounds,
                    synthesis_stage=se.stage,
                    synthesis_raw="",
                    synthesis_error=str(se),
                    synthesis_input=synthesis_input,
                    curated_sources=curated_sources,
                ),
            ) from e

        if self.emitter is not None:
            self.emitter.emit(
                ProgressEvent(stage="done", current=1, total=1, message=f"Done (stop_reason={stop_reason})")
            )

        combined_plan = {"tasks": []}
        tasks_out = []
        for p in plans:
            if not isinstance(p, dict):
                continue
            for t in p.get("tasks") or []:
                if isinstance(t, dict):
                    tasks_out.append(t)
        if tasks_out:
            combined_plan["tasks"] = tasks_out

        return DeepResearchOutcome(
            query=query,
            plan=combined_plan,
            planner_raw=planner_raw,
            planner_error=planner_error,
            tasks=all_tasks,
            results=all_results,
            citations=citations,
            report_markdown=report,
            report_json=report_json,
            rounds=rounds,
            synthesis_input=synthesis_input,
            curated_sources=curated_sources,
        )

    def _refine_draft(
        self,
        *,
        query: str,
        report_type: ReportType,
        draft: str,
        findings: list[dict[str, Any]],
    ) -> str:
        findings_json = json.dumps(findings, ensure_ascii=False)
        prompt = f"""You are refining a research draft based on new findings.

Query: {query}
Report type: {report_type.value}

Current draft:
{draft if draft.strip() else "(empty - first iteration)"}

New findings (JSON):
{findings_json}

STRICT RULES:
- Do NOT add new factual claims unless DIRECTLY supported by the New findings above
- If information is uncertain or unverified, mark it as [TBD] or [needs verification]
- Remove or update any information that contradicts the new findings
- Keep the draft concise (max 2000 words)

FORMAT:
End the draft with a "## Still Missing" section listing:
- Information gaps that need more research
- Claims that need verification
- Topics not yet covered

Return ONLY the updated draft text. No JSON, no code fences.
"""
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2500,
        )
        return (resp.choices[0].message.content or "").strip()

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

    def _collect_citations_from_traces(self, results: list[WorkerResult]) -> list[str]:
        urls: set[str] = set()
        for r in results:
            for u in getattr(r, "citations", ()) or ():
                if isinstance(u, str) and u.startswith("http"):
                    urls.add(u)
        return sorted(urls)

    def _collect_evidence_urls(self, results: list[WorkerResult]) -> list[str]:
        urls: set[str] = set()
        for r in results:
            ev = getattr(r, "evidence", ()) or ()
            for item in ev:
                if not isinstance(item, dict):
                    continue
                u = item.get("url")
                if isinstance(u, str) and u.startswith("http"):
                    urls.add(u)
        return sorted(urls)

    def _collect_domains(self, citations: list[str]) -> list[str]:
        domains: set[str] = set()
        for u in citations:
            if not isinstance(u, str) or not u.startswith("http"):
                continue
            try:
                netloc = urlparse(u).netloc.lower().strip()
            except Exception:
                continue
            if netloc:
                domains.add(netloc)
        return sorted(domains)

    def _build_synthesis_input(
        self,
        *,
        query: str,
        findings: list[dict[str, Any]],
        allowed_urls: list[str],
        curated_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        allowed = set(allowed_urls)
        sources: dict[str, dict[str, Any]] = {}
        by_task: list[dict[str, Any]] = []

        for f in findings:
            if not isinstance(f, dict):
                continue
            task_id = str(f.get("task_id") or "").strip()
            urls = f.get("citations")
            urls_list = [u for u in urls if isinstance(u, str) and u in allowed] if isinstance(urls, list) else []
            src = f.get("sources")
            if isinstance(src, dict):
                for url, meta in src.items():
                    if not (isinstance(url, str) and url in allowed and isinstance(meta, dict)):
                        continue
                    title = meta.get("title") if isinstance(meta.get("title"), str) else ""
                    snippet = meta.get("snippet") if isinstance(meta.get("snippet"), str) else ""
                    sources[url] = {
                        "url": url,
                        "domain": urlparse(url).netloc,
                        "title": (title or "").strip(),
                        "snippet": sanitize_snippet(snippet),
                    }

            top_sources = []
            for u in urls_list:
                if u in sources:
                    top_sources.append(sources[u])
                if len(top_sources) >= 8:
                    break

            if task_id:
                by_task.append(
                    {
                        "task_id": task_id,
                        "success": bool(f.get("success", True)),
                        "web_search_calls": int(f.get("web_search_calls") or 0),
                        "citations_count": len(urls_list),
                        "citations": urls_list[:12],
                        "top_sources": top_sources,
                        "output": (str(f.get("output") or "")[:4000]),
                    }
                )

        allowed_sources = list(sources.values())
        allowed_sources.sort(key=lambda x: (x.get("domain") or "", x.get("url") or ""))
        out: dict[str, Any] = {"query": query, "allowed_sources": allowed_sources, "tasks": by_task}
        if curated_sources is not None:
            out["curated_sources"] = curated_sources
        return out

    def _build_synthesis_findings(
        self,
        *,
        results: list[WorkerResult],
        allowed_urls: set[str],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in results:
            sources = getattr(r, "sources", {}) or {}
            filtered_sources: dict[str, dict[str, str]] = {}
            if isinstance(sources, dict):
                for url, meta in sources.items():
                    if isinstance(url, str) and url in allowed_urls and isinstance(meta, dict):
                        filtered_sources[url] = {
                            "title": str(meta.get("title") or "").strip(),
                            "snippet": sanitize_snippet(str(meta.get("snippet") or "")),
                        }
            out.append(
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "citations": [
                        u
                        for u in (list(r.citations) if r.citations else [])
                        if isinstance(u, str) and u in allowed_urls
                    ],
                    "sources": filtered_sources,
                    "web_search_calls": int(r.web_search_calls or 0),
                }
            )
        return out

    def _build_curated_sources(
        self,
        *,
        results: list[WorkerResult],
        max_total: int,
        max_per_domain: int,
        min_per_task: int,
    ) -> list[dict[str, Any]]:
        max_total = max(0, int(max_total))
        if max_total <= 0:
            return []
        max_per_domain = max(0, int(max_per_domain))
        min_per_task = max(0, int(min_per_task))

        per_task: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            task_id = str(getattr(r, "task_id", "") or "").strip()
            if not task_id:
                continue
            sources = getattr(r, "sources", {}) or {}
            best_by_url: dict[str, dict[str, Any]] = {}
            rank = 0
            for call in getattr(r, "web_search_trace", ()) or ():
                if not isinstance(call, dict):
                    continue
                items = call.get("results")
                if not isinstance(items, list):
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    url = it.get("url")
                    if not (isinstance(url, str) and url.startswith("http")):
                        continue
                    rank += 1
                    score = it.get("score")
                    score_f = float(score) if isinstance(score, (int, float)) else 0.0
                    title = it.get("title")
                    snippet = it.get("snippet")
                    meta = sources.get(url) if isinstance(sources, dict) else None
                    if isinstance(meta, dict):
                        title = meta.get("title") if isinstance(meta.get("title"), str) else title
                        snippet = meta.get("snippet") if isinstance(meta.get("snippet"), str) else snippet
                    entry = best_by_url.get(url)
                    if entry is None or score_f > float(entry.get("score") or 0.0):
                        best_by_url[url] = {
                            "url": url,
                            "domain": urlparse(url).netloc,
                            "title": (str(title or "")).strip(),
                            "snippet": sanitize_snippet(str(snippet or "")),
                            "score": score_f,
                            "task_id": task_id,
                            "rank_within_task": rank,
                        }
            candidates = list(best_by_url.values())
            candidates.sort(key=lambda x: (-float(x.get("score") or 0.0), int(x.get("rank_within_task") or 0)))
            per_task[task_id] = candidates

        selected: list[dict[str, Any]] = []
        selected_urls: set[str] = set()
        domain_counts: dict[str, int] = {}

        def can_add(item: dict[str, Any]) -> bool:
            url = item.get("url")
            if not isinstance(url, str) or url in selected_urls:
                return False
            domain = str(item.get("domain") or "")
            if max_per_domain and domain_counts.get(domain, 0) >= max_per_domain:
                return False
            return True

        task_ids = list(per_task.keys())
        per_task_counts: dict[str, int] = {tid: 0 for tid in task_ids}

        made_progress = True
        while made_progress and len(selected) < max_total and min_per_task:
            made_progress = False
            for tid in task_ids:
                if len(selected) >= max_total:
                    break
                if per_task_counts.get(tid, 0) >= min_per_task:
                    continue
                items = per_task.get(tid) or []
                while items and not can_add(items[0]):
                    items.pop(0)
                if not items:
                    continue
                item = items.pop(0)
                if can_add(item):
                    selected.append(item)
                    selected_urls.add(item["url"])
                    domain_counts[item["domain"]] = domain_counts.get(item["domain"], 0) + 1
                    per_task_counts[tid] = per_task_counts.get(tid, 0) + 1
                    made_progress = True

        made_progress = True
        while made_progress and len(selected) < max_total:
            made_progress = False
            for tid in task_ids:
                if len(selected) >= max_total:
                    break
                items = per_task.get(tid) or []
                while items and not can_add(items[0]):
                    items.pop(0)
                if not items:
                    continue
                item = items.pop(0)
                if can_add(item):
                    selected.append(item)
                    selected_urls.add(item["url"])
                    domain_counts[item["domain"]] = domain_counts.get(item["domain"], 0) + 1
                    made_progress = True

        return selected

