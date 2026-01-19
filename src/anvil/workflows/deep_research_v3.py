from __future__ import annotations

import json
from typing import Any

from common import llm
from common.events import ProgressEvent

from anvil.workflows.deep_research_utils import select_top_findings
from anvil.workflows.deep_research_types import DeepResearchOutcome, DeepResearchRunError, PlanningError, SynthesisError
from anvil.workflows.deep_research_workflow import DeepResearchWorkflow as _LegacyDeepResearchWorkflow
from anvil.workflows.iterative_loop import ReportType, detect_report_type


class DeepResearchWorkflow(_LegacyDeepResearchWorkflow):
    """
    Draft-centric deep research loop (v3).

    Inherits helper methods from the legacy workflow to keep the refactor
    incremental, but replaces the round/memo orchestration with a dynamic loop.
    """

    def run(self, query: str):
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
        all_results = []
        all_tasks = []
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
            planned_queries: list[str] = []
            if isinstance(tasks_list, list):
                for t in tasks_list:
                    if not isinstance(t, dict):
                        continue
                    q = t.get("search_query")
                    if isinstance(q, str) and q.strip():
                        planned_queries.append(_norm_query(q))

            novel = [q for q in planned_queries if q and q not in seen_queries]
            if not novel and iteration > 0:
                stop_reason = "no_novel_queries"
                break
            for q in novel:
                seen_queries.add(q)

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
