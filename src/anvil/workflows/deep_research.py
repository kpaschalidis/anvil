from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from common import llm
from common.events import EventEmitter, ProgressEvent, ResearchPlanEvent, WorkerCompletedEvent
from anvil.subagents.parallel import ParallelWorkerRunner, WorkerTask
from anvil.subagents.task_tool import SubagentRunner
from anvil.subagents.parallel import WorkerResult


class PlanningError(RuntimeError):
    def __init__(self, message: str, *, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class SynthesisError(RuntimeError):
    def __init__(self, message: str, *, raw: str = "", stage: str = "synthesize"):
        super().__init__(message)
        self.raw = raw
        self.stage = stage


class DeepResearchRunError(RuntimeError):
    def __init__(self, message: str, *, outcome: "DeepResearchOutcome | None" = None):
        super().__init__(message)
        self.outcome = outcome


def sanitize_snippet(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    # Drop markdown links with relative URLs (e.g. [x](/docs/...)), keep label.
    s = re.sub(r"\[([^\]]+)\]\((/[^)]+)\)", r"\1", s)
    # Drop standalone relative URLs in parentheses.
    s = re.sub(r"\((/[^)]+)\)", "", s)

    # Remove common inline markdown/nav tokens that Tavily snippets can include.
    s = s.replace("#####", " ")
    s = s.replace("####", " ")
    s = s.replace("###", " ")
    s = s.replace("##", " ")
    s = s.replace("#", " ")
    # Treat " * " as a bullet separator, not emphasis.
    s = re.sub(r"\s\*\s", " ", s)

    cleaned_lines: list[str] = []
    for line in s.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip common markdown formatting prefixes.
        line = re.sub(r"^\s*#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[*+-]\s+", "", line)
        line = re.sub(r"^\s*\d+\.\s+", "", line)
        if line:
            cleaned_lines.append(line)

    s = " ".join(cleaned_lines) if cleaned_lines else s
    s = " ".join(s.split())
    if len(s) > 360:
        s = s[:360].rstrip() + "…"
    return s


@dataclass(frozen=True, slots=True)
class DeepResearchConfig:
    model: str = "gpt-4o"
    max_workers: int = 5
    worker_max_iterations: int = 6
    worker_timeout_s: float = 120.0
    max_tasks: int = 5
    page_size: int = 8
    max_pages: int = 3
    target_web_search_calls: int = 2
    max_web_search_calls: int = 6
    min_total_domains: int = 3
    enable_worker_continuation: bool = False
    max_worker_continuations: int = 0
    enable_deep_read: bool = False
    max_web_extract_calls: int = 3
    extract_max_chars: int = 20_000
    require_quote_per_claim: bool = False
    multi_pass_synthesis: bool = False
    enable_round2: bool = False
    round2_max_tasks: int = 3
    verify_max_tasks: int = 0
    require_citations: bool = True
    min_total_citations: int = 3
    strict_all: bool = True
    best_effort: bool = False
    report_min_unique_citations_target: int = 0
    report_min_unique_domains_target: int = 0
    report_findings_target: int = 5
    coverage_mode: str = "warn"  # "warn" or "error"
    curated_sources_max_total: int = 0
    curated_sources_max_per_domain: int = 0
    curated_sources_min_per_task: int = 0


@dataclass(frozen=True, slots=True)
class DeepResearchOutcome:
    query: str
    plan: dict[str, Any]
    tasks: list[WorkerTask]
    results: list[WorkerResult]
    citations: list[str]
    report_markdown: str
    report_json: dict[str, Any] | None = None
    planner_raw: str = ""
    planner_error: str | None = None
    gap_plan: dict[str, Any] | None = None
    gap_planner_raw: str = ""
    gap_planner_error: str | None = None
    verify_plan: dict[str, Any] | None = None
    verify_planner_raw: str = ""
    verify_planner_error: str | None = None
    synthesis_stage: str | None = None
    synthesis_raw: str = ""
    synthesis_error: str | None = None
    synthesis_input: dict[str, Any] | None = None
    curated_sources: list[dict[str, Any]] | None = None


def _planning_prompt(query: str, *, max_tasks: int) -> str:
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
- Provide 3 to 8 findings for this section.
- Every finding must include 2-3 evidence items (prefer 3 when possible).
- Every evidence.url must appear in the provided Evidence list.
- Every evidence.quote must be a substring copied from that URL's excerpt.
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


class DeepResearchWorkflow:
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

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="plan", current=0, total=None, message="Planning searches"))

        plan, planner_raw, planner_error = self._plan(query, max_tasks=self.config.max_tasks, min_tasks=3)
        if self.emitter is not None:
            tasks = plan.get("tasks") if isinstance(plan, dict) else None
            if isinstance(tasks, list):
                summarized = []
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    summarized.append(
                        {
                            "id": t.get("id"),
                            "search_query": t.get("search_query"),
                            "instructions": t.get("instructions"),
                        }
                    )
                if summarized:
                    self.emitter.emit(ResearchPlanEvent(tasks=summarized))
        round1_tasks = self._to_worker_tasks(query, plan)

        if self.emitter is not None:
            self.emitter.emit(
                ProgressEvent(
                    stage="workers",
                    current=0,
                    total=len(round1_tasks),
                    message=f"Running {len(round1_tasks)} tasks (max concurrency: {self.config.max_workers})",
                )
            )

        results = self.parallel_runner.spawn_parallel(
            round1_tasks,
            max_workers=self.config.max_workers,
            timeout=self.config.worker_timeout_s,
            allow_writes=False,
            max_web_search_calls=max(1, int(self.config.max_web_search_calls)),
            max_web_extract_calls=(
                max(0, int(self.config.max_web_extract_calls)) if self.config.enable_deep_read else 0
            ),
            extract_max_chars=int(self.config.extract_max_chars),
            on_result=(self._emit_worker_completed if self.emitter is not None else None),
        )

        results = self._maybe_continue_workers(
            round1_tasks,
            results,
            stage_label="workers",
            message_prefix="Continuing round-1 tasks",
        )

        results = self._apply_worker_invariants(results)
        citations = (
            self._collect_evidence_urls(results)
            if self.config.enable_deep_read
            else self._collect_citations_from_traces(results)
        )
        domains = self._collect_domains(citations)
        failures = [r for r in results if not r.success]

        if self.config.strict_all and failures and not self.config.best_effort:
            raise RuntimeError(
                "Deep research failed because one or more workers failed.\n\n"
                f"Diagnostics:\n{self._format_worker_diagnostics(results)}"
            )

        if self.config.require_citations and not self.config.best_effort:
            if len(citations) < self.config.min_total_citations:
                raise RuntimeError(
                    "Deep research requires web citations but none (or too few) were collected.\n"
                    "Fix: run `uv sync --extra search` and ensure `TAVILY_API_KEY` is set.\n\n"
                    f"Diagnostics:\n{self._format_worker_diagnostics(results)}"
                )
            if len(domains) < max(0, int(self.config.min_total_domains)):
                raise RuntimeError(
                    "Deep research requires broader source coverage but too few unique domains were collected.\n"
                    f"Need >= {self.config.min_total_domains} domains, got {len(domains)}.\n\n"
                    f"Diagnostics:\n{self._format_worker_diagnostics(results)}"
                )

        findings: list[dict[str, Any]] = []
        for r in results:
            findings.append(
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

        gap_plan = None
        gap_planner_raw = ""
        gap_planner_error = None
        round2_tasks: list[WorkerTask] = []
        if self.config.enable_round2 and not self.config.best_effort:
            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(stage="gap", current=0, total=None, message="Planning follow-up searches")
                )
            gap_plan, gap_planner_raw, gap_planner_error = self._gap_fill_plan(query, findings)
            round2_tasks = self._to_worker_tasks(query, gap_plan) if gap_plan else []
            if round2_tasks:
                if self.emitter is not None:
                    self.emitter.emit(
                        ProgressEvent(
                            stage="workers",
                            current=0,
                            total=len(round2_tasks),
                            message=f"Running {len(round2_tasks)} follow-up tasks (max concurrency: {self.config.max_workers})",
                        )
                    )
                more = self.parallel_runner.spawn_parallel(
                    round2_tasks,
                    max_workers=self.config.max_workers,
                    timeout=self.config.worker_timeout_s,
                    allow_writes=False,
                    max_web_search_calls=max(1, int(self.config.max_web_search_calls)),
                    max_web_extract_calls=(
                        max(0, int(self.config.max_web_extract_calls)) if self.config.enable_deep_read else 0
                    ),
                    extract_max_chars=int(self.config.extract_max_chars),
                    on_result=(self._emit_worker_completed if self.emitter is not None else None),
                )
                more = self._maybe_continue_workers(
                    round2_tasks,
                    more,
                    stage_label="workers",
                    message_prefix="Continuing round-2 tasks",
                )
                more = self._apply_worker_invariants(more)
                results = list(results) + list(more)
                citations = (
                    self._collect_evidence_urls(results)
                    if self.config.enable_deep_read
                    else self._collect_citations_from_traces(results)
                )
                failures = [r for r in results if not r.success]
                if self.config.strict_all and failures:
                    raise RuntimeError(
                        "Deep research failed because one or more workers failed.\n\n"
                        f"Diagnostics:\n{self._format_worker_diagnostics(results)}"
                    )
                findings = []
                for r in results:
                    findings.append(
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

        verify_plan = None
        verify_planner_raw = ""
        verify_planner_error = None
        verify_tasks: list[WorkerTask] = []
        if int(self.config.verify_max_tasks) > 0 and not self.config.best_effort:
            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(stage="verify", current=0, total=None, message="Planning verification searches")
                )
            verify_plan, verify_planner_raw, verify_planner_error = self._verification_plan(query, findings)
            verify_tasks = self._to_worker_tasks(query, verify_plan) if verify_plan else []
            if verify_tasks:
                if self.emitter is not None:
                    self.emitter.emit(
                        ProgressEvent(
                            stage="workers",
                            current=0,
                            total=len(verify_tasks),
                            message=f"Running {len(verify_tasks)} verification tasks (max concurrency: {self.config.max_workers})",
                        )
                    )
                    more = self.parallel_runner.spawn_parallel(
                        verify_tasks,
                    max_workers=self.config.max_workers,
                    timeout=self.config.worker_timeout_s,
                    allow_writes=False,
                    max_web_search_calls=max(1, int(self.config.max_web_search_calls)),
                    max_web_extract_calls=(
                        max(0, int(self.config.max_web_extract_calls)) if self.config.enable_deep_read else 0
                    ),
                        extract_max_chars=int(self.config.extract_max_chars),
                        on_result=(self._emit_worker_completed if self.emitter is not None else None),
                    )
                more = self._maybe_continue_workers(
                    verify_tasks,
                    more,
                    stage_label="workers",
                    message_prefix="Continuing verification tasks",
                )
                more = self._apply_worker_invariants(more)
                results = list(results) + list(more)
                citations = (
                    self._collect_evidence_urls(results)
                    if self.config.enable_deep_read
                    else self._collect_citations_from_traces(results)
                )
                failures = [r for r in results if not r.success]
                if self.config.strict_all and failures:
                    raise RuntimeError(
                        "Deep research failed because one or more workers failed.\n\n"
                        f"Diagnostics:\n{self._format_worker_diagnostics(results)}"
                    )
                findings = []
                for r in results:
                    findings.append(
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

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="synthesize", current=0, total=None, message="Synthesizing report"))

        curated_sources: list[dict[str, Any]] | None = None
        synthesis_findings = findings
        synthesis_allowed_urls = list(citations)
        if not self.config.require_quote_per_claim and int(self.config.curated_sources_max_total) > 0:
            curated_sources = self._build_curated_sources(
                results=results,
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
                synthesis_findings = findings
            else:
                synthesis_findings = self._build_synthesis_findings(
                    results=results,
                    allowed_urls=set(synthesis_allowed_urls),
                )

        synthesis_input = self._build_synthesis_input(
            query=query,
            findings=synthesis_findings,
            allowed_urls=sorted(set(citations)),
            curated_sources=curated_sources,
        )

        try:
            report, report_json = self._synthesize_and_render(query, synthesis_findings, synthesis_allowed_urls)
        except SynthesisError as e:
            combined_plan = plan
            if round2_tasks:
                combined_plan = (
                    {"tasks": (plan.get("tasks") or []) + (gap_plan.get("tasks") or [])} if gap_plan else plan
                )
            if verify_tasks and isinstance(combined_plan, dict):
                combined_plan = {
                    "tasks": (combined_plan.get("tasks") or []) + (verify_plan.get("tasks") or [])  # type: ignore[union-attr]
                } if verify_plan else combined_plan
            raise DeepResearchRunError(
                str(e),
                outcome=DeepResearchOutcome(
                    query=query,
                    plan=combined_plan,
                    planner_raw=planner_raw,
                    planner_error=planner_error,
                    tasks=round1_tasks + round2_tasks + verify_tasks,
                    results=results,
                    citations=citations,
                    report_markdown="",
                    report_json=None,
                    gap_plan=gap_plan,
                    gap_planner_raw=gap_planner_raw,
                    gap_planner_error=gap_planner_error,
                    verify_plan=verify_plan,
                    verify_planner_raw=verify_planner_raw,
                    verify_planner_error=verify_planner_error,
                    synthesis_stage=e.stage,
                    synthesis_raw=e.raw,
                    synthesis_error=str(e),
                    synthesis_input=synthesis_input,
                    curated_sources=curated_sources,
                ),
            ) from e

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="done", current=1, total=1, message="Done"))

        combined_plan = plan
        if round2_tasks:
            combined_plan = {"tasks": (plan.get("tasks") or []) + (gap_plan.get("tasks") or [])} if gap_plan else plan
        if verify_tasks and isinstance(combined_plan, dict):
            combined_plan = {
                "tasks": (combined_plan.get("tasks") or []) + (verify_plan.get("tasks") or [])  # type: ignore[union-attr]
            } if verify_plan else combined_plan

        return DeepResearchOutcome(
            query=query,
            plan=combined_plan,
            planner_raw=planner_raw,
            planner_error=planner_error,
            tasks=round1_tasks + round2_tasks + verify_tasks,
            results=results,
            citations=citations,
            report_markdown=report,
            report_json=report_json,
            gap_plan=gap_plan,
            gap_planner_raw=gap_planner_raw,
            gap_planner_error=gap_planner_error,
            verify_plan=verify_plan,
            verify_planner_raw=verify_planner_raw,
            verify_planner_error=verify_planner_error,
            synthesis_input=synthesis_input,
            curated_sources=curated_sources,
        )

    def _plan(self, query: str, *, max_tasks: int, min_tasks: int) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _planning_prompt(query, max_tasks=max(1, int(max_tasks)))}],
            temperature=0.2,
            max_tokens=800,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            msg = (
                "Planner returned an empty response. "
                "Check that your LLM provider API key is set for the selected model."
            )
            if not self.config.best_effort:
                raise PlanningError(msg, raw=content)
            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(stage="plan", current=0, total=None, message=f"WARNING: {msg}")
                )
            return self._fallback_plan(query), content, msg
        try:
            plan = self._parse_planner_json(content)
        except Exception as e:
            msg = f"Planner returned invalid JSON: {e}"
            if not self.config.best_effort:
                raise PlanningError(msg, raw=content) from e
            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(
                        stage="plan",
                        current=0,
                        total=None,
                        message=f"WARNING: {msg}. Using fallback plan (best-effort).",
                    )
                )
            return self._fallback_plan(query), content, msg

        try:
            validated = self._validate_plan(plan, min_tasks=min_tasks)
        except PlanningError as e:
            if not self.config.best_effort:
                raise PlanningError(str(e), raw=content) from None
            msg = str(e)
            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(
                        stage="plan",
                        current=0,
                        total=None,
                        message=f"WARNING: {msg}. Using fallback plan (best-effort).",
                    )
                )
            return self._fallback_plan(query), content, msg

        return validated, content, None

    def _continuation_prompt(
        self,
        *,
        base_prompt: str,
        prior_output: str,
        prior_citations: list[str],
        prior_evidence_urls: list[str],
        additional_calls: int,
        remaining_extracts: int,
    ) -> str:
        prior = "\n".join(f"- {u}" for u in prior_citations[:15])
        extra = max(1, int(additional_calls))
        extract_block = ""
        if bool(self.config.enable_deep_read) and int(remaining_extracts) > 0:
            already_read = "\n".join(f"- {u}" for u in prior_evidence_urls[:15])
            extract_block = (
                "\n"
                + f"After searching, call `web_extract` on up to {int(remaining_extracts)} NEW URLs (pages you have not extracted yet).\n"
                + f"Use `max_chars={max(1, int(self.config.extract_max_chars))}`.\n"
                + "Prefer diverse, reputable domains and avoid duplicates.\n"
                + "Already extracted URLs (do not re-extract):\n"
                + (already_read if already_read else "(none)")
                + "\n"
            )
        return (
            base_prompt.strip()
            + "\n\n"
            + "Continue researching this same task.\n"
            + f"Make ~{extra} additional `web_search` calls (if possible), focusing on NEW domains and NEW query variants.\n"
            + f"Use pagination (page=1..{max(1, int(self.config.max_pages))}) and page_size={max(1, int(self.config.page_size))}.\n"
            + "Avoid reusing URLs you already collected.\n\n"
            + "Already collected URLs (do not reuse):\n"
            + (prior if prior else "(none)")
            + (extract_block if extract_block else "")
            + "\n\n"
            + "Append new bullet points and cite any new URLs you used.\n"
            + (f"\n\nPrevious notes:\n{prior_output.strip()}" if (prior_output or "").strip() else "")
        )

    def _merge_worker_results(self, a: WorkerResult, b: WorkerResult) -> WorkerResult:
        citations = tuple(sorted(set(a.citations or ()) | set(b.citations or ())))
        sources = dict(getattr(a, "sources", {}) or {})
        sources.update(dict(getattr(b, "sources", {}) or {}))
        trace = tuple((getattr(a, "web_search_trace", ()) or ()) + (getattr(b, "web_search_trace", ()) or ()))
        extract_trace = tuple((getattr(a, "web_extract_trace", ()) or ()) + (getattr(b, "web_extract_trace", ()) or ()))
        evidence = tuple((getattr(a, "evidence", ()) or ()) + (getattr(b, "evidence", ()) or ()))
        output_parts = []
        if (a.output or "").strip():
            output_parts.append(a.output.strip())
        if (b.output or "").strip():
            output_parts.append(b.output.strip())
        duration_ms = None
        if getattr(a, "duration_ms", None) is not None or getattr(b, "duration_ms", None) is not None:
            duration_ms = int((getattr(a, "duration_ms", 0) or 0) + (getattr(b, "duration_ms", 0) or 0))
        return WorkerResult(
            task_id=a.task_id,
            output="\n\n".join(output_parts),
            citations=citations,
            sources=sources,
            web_search_calls=int(getattr(a, "web_search_calls", 0) or 0) + int(getattr(b, "web_search_calls", 0) or 0),
            web_search_trace=trace,
            web_extract_calls=int(getattr(a, "web_extract_calls", 0) or 0) + int(getattr(b, "web_extract_calls", 0) or 0),
            web_extract_trace=extract_trace,
            evidence=evidence,
            iterations=int(getattr(a, "iterations", 0) or 0) + int(getattr(b, "iterations", 0) or 0),
            duration_ms=duration_ms,
            success=a.success and b.success,
            error=a.error or b.error,
        )

    def _maybe_continue_workers(
        self,
        tasks: list[WorkerTask],
        results: list[WorkerResult],
        *,
        stage_label: str,
        message_prefix: str,
    ) -> list[WorkerResult]:
        if not self.config.enable_worker_continuation:
            return results

        if self.config.best_effort:
            return results
        target = max(1, int(self.config.target_web_search_calls))
        if target <= 1:
            return results
        max_total = max(1, int(self.config.max_web_search_calls))
        max_total_extract = max(0, int(self.config.max_web_extract_calls)) if bool(self.config.enable_deep_read) else 0
        max_rounds = max(0, int(self.config.max_worker_continuations))
        if max_rounds <= 0:
            return results

        task_by_id = {t.id: t for t in tasks}
        results_by_id = {r.task_id: r for r in results}

        for _ in range(max_rounds):
            todo: list[WorkerTask] = []
            for r in results_by_id.values():
                if not r.success:
                    continue
                current_calls = int(getattr(r, "web_search_calls", 0) or 0)
                remaining = max_total - current_calls
                need = target - current_calls
                if need <= 0 or remaining <= 0:
                    continue
                t = task_by_id.get(r.task_id)
                if t is None:
                    continue
                current_extract = int(getattr(r, "web_extract_calls", 0) or 0)
                remaining_extract = max(0, max_total_extract - current_extract)
                prompt = self._continuation_prompt(
                    base_prompt=t.prompt,
                    prior_output=r.output,
                    prior_citations=list(getattr(r, "citations", ()) or ()),
                    prior_evidence_urls=[
                        str(ev.get("url"))
                        for ev in (getattr(r, "evidence", ()) or ())
                        if isinstance(ev, dict) and isinstance(ev.get("url"), str)
                    ],
                    additional_calls=min(need, remaining),
                    remaining_extracts=remaining_extract,
                )
                todo.append(
                    WorkerTask(
                        id=r.task_id,
                        prompt=prompt,
                        agent_name=t.agent_name,
                        max_iterations=t.max_iterations,
                        max_web_search_calls=remaining,
                        max_web_extract_calls=remaining_extract,
                    )
                )

            if not todo:
                break

            if self.emitter is not None:
                self.emitter.emit(
                    ProgressEvent(
                        stage=stage_label,
                        current=0,
                        total=len(todo),
                        message=f"{message_prefix}: {len(todo)} task(s)",
                    )
                )

            more = self.parallel_runner.spawn_parallel(
                todo,
                max_workers=self.config.max_workers,
                timeout=self.config.worker_timeout_s,
                allow_writes=False,
                max_web_search_calls=None,
                max_web_extract_calls=max_total_extract,
                extract_max_chars=int(self.config.extract_max_chars),
                on_result=(self._emit_worker_completed if self.emitter is not None else None),
            )
            for nr in more:
                prev = results_by_id.get(nr.task_id)
                if prev is None:
                    results_by_id[nr.task_id] = nr
                    continue
                if not nr.success:
                    continue
                results_by_id[nr.task_id] = self._merge_worker_results(prev, nr)

        ordered: list[WorkerResult] = []
        for r in results:
            ordered.append(results_by_id.get(r.task_id, r))
        return ordered

    def _emit_worker_completed(self, result: WorkerResult) -> None:
        if self.emitter is None:
            return
        urls = set(getattr(result, "citations", ()) or ())
        domains = {urlparse(u).netloc for u in urls if isinstance(u, str) and u.startswith("http")}
        evidence = getattr(result, "evidence", ()) or ()
        self.emitter.emit(
            WorkerCompletedEvent(
                task_id=str(getattr(result, "task_id", "") or ""),
                success=bool(getattr(result, "success", False)),
                web_search_calls=int(getattr(result, "web_search_calls", 0) or 0),
                web_extract_calls=int(getattr(result, "web_extract_calls", 0) or 0),
                citations=len(urls),
                domains=len(domains),
                evidence=len(evidence) if isinstance(evidence, (list, tuple)) else 0,
                duration_ms=getattr(result, "duration_ms", None),
                error=str(getattr(result, "error", "") or ""),
            )
        )

    def _gap_fill_plan(self, query: str, findings: list[dict[str, Any]]) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": _gap_fill_prompt(query, findings, max_tasks=max(0, int(self.config.round2_max_tasks))),
                }
            ],
            temperature=0.2,
            max_tokens=800,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise PlanningError("Gap planner returned an empty response.", raw=content)
        try:
            plan = self._parse_planner_json(content)
        except Exception as e:
            raise PlanningError(f"Gap planner returned invalid JSON: {e}", raw=content) from e
        validated = self._validate_plan(plan, min_tasks=0)
        tasks = validated.get("tasks") or []
        # Prefix task IDs to avoid collisions with round 1.
        for t in tasks:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and not t["id"].startswith("r2_"):
                t["id"] = f"r2_{t['id']}"
        return {"tasks": tasks[: max(0, int(self.config.round2_max_tasks))]}, content, None

    def _verification_plan(self, query: str, findings: list[dict[str, Any]]) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": _verification_prompt(
                        query,
                        findings,
                        max_tasks=max(0, int(self.config.verify_max_tasks)),
                    ),
                }
            ],
            temperature=0.2,
            max_tokens=800,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise PlanningError("Verification planner returned an empty response.", raw=content)
        try:
            plan = self._parse_planner_json(content)
        except Exception as e:
            raise PlanningError(f"Verification planner returned invalid JSON: {e}", raw=content) from e
        validated = self._validate_plan(plan, min_tasks=0)
        tasks = validated.get("tasks") or []
        for t in tasks:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and not t["id"].startswith("v_"):
                t["id"] = f"v_{t['id']}"
        return {"tasks": tasks[: max(0, int(self.config.verify_max_tasks))]}, content, None

    def _parse_planner_json(self, content: str) -> Any:
        try:
            return json.loads(content)
        except Exception:
            pass

        stripped = content.strip()
        if stripped.startswith("```"):
            inner = self._extract_single_code_fence(stripped)
            if inner is not None:
                return json.loads(inner)

        raise ValueError("content is not a JSON object")

    def _extract_single_code_fence(self, text: str) -> str | None:
        lines = text.splitlines()
        if not lines:
            return None
        if not lines[0].startswith("```"):
            return None
        # Allow ```json or ```JSON etc.
        closing_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "```":
                closing_idx = i
                break
        if closing_idx is None:
            return None
        inner = "\n".join(lines[1:closing_idx]).strip()
        if not inner:
            return None
        return inner

    def _fallback_plan(self, query: str) -> dict[str, Any]:
        return {
            "tasks": [
                {
                    "id": "overview",
                    "search_query": query,
                    "instructions": "Find high-quality overview sources and key facts with links.",
                },
                {
                    "id": "comparison",
                    "search_query": f"{query} comparison",
                    "instructions": "Find comparisons, pros/cons, and alternatives with links.",
                },
                {
                    "id": "recent",
                    "search_query": f"{query} 2024 2025",
                    "instructions": "Find recent changes/news and notable developments with links.",
                },
            ]
        }

    def _validate_plan(self, plan: Any, *, min_tasks: int = 3) -> dict[str, Any]:
        if not isinstance(plan, dict):
            raise PlanningError("Planner output must be a JSON object")
        tasks = plan.get("tasks")
        if not isinstance(tasks, list):
            raise PlanningError("Planner output must include `tasks` as a list")

        validated_tasks: list[dict[str, str]] = []
        for idx, t in enumerate(tasks):
            if not isinstance(t, dict):
                continue
            task_id = str(t.get("id") or "").strip()
            search_query = str(t.get("search_query") or "").strip()
            instructions = str(t.get("instructions") or "").strip()
            if not task_id:
                task_id = f"task_{idx}"
            if not search_query or not instructions:
                continue
            validated_tasks.append(
                {"id": task_id, "search_query": search_query, "instructions": instructions}
            )

        if len(validated_tasks) < int(min_tasks):
            raise PlanningError(f"Planner output did not produce enough valid tasks (need >= {min_tasks})")

        return {"tasks": validated_tasks[:10]}

    def _to_worker_tasks(self, query: str, plan: dict[str, Any]) -> list[WorkerTask]:
        tasks = plan.get("tasks") if isinstance(plan, dict) else None
        if not isinstance(tasks, list) or not tasks:
            if not self.config.best_effort:
                raise PlanningError("Plan produced no tasks")
            return [
                WorkerTask(
                    id="search",
                    prompt=f"Use `web_search` for: {query}. Return key findings with URLs.",
                    max_iterations=self.config.worker_max_iterations,
                )
            ]
        worker_tasks: list[WorkerTask] = []
        for idx, t in enumerate(tasks[:10]):
            if not isinstance(t, dict):
                continue
            task_id = str(t.get("id") or f"task_{idx}")
            search_query = str(t.get("search_query") or "").strip()
            instructions = str(t.get("instructions") or "").strip()
            if not search_query:
                continue
            deep_read = bool(self.config.enable_deep_read)
            read_block = ""
            if deep_read:
                read_block = (
                    "\nDeep mode: after you find promising URLs, you MUST call `web_extract` on the best sources.\n"
                    f"- Extract up to {max(1, int(self.config.max_web_extract_calls))} pages.\n"
                    f"- Use `max_chars={max(1, int(self.config.extract_max_chars))}`.\n"
                    "- Prefer diverse, reputable domains and avoid duplicates.\n"
                )
            prompt = (
                "Use the `web_search` tool to gather sources and extract key facts.\n"
                f"Aim for ~{max(1, int(self.config.target_web_search_calls))} `web_search` calls.\n"
                f"Use pagination (page=1..{max(1, int(self.config.max_pages))}) and page_size={max(1, int(self.config.page_size))}.\n"
                f"Aim for 2+ distinct query variants (refine queries as you learn).\n"
                f"{read_block}"
                "Stop searching once you have enough evidence and then write a concise note.\n\n"
                f"Search query: {search_query}\n\n"
                f"Instructions: {instructions}\n\n"
                "Return a short Markdown note with bullet points and cite URLs.\n"
            )
            worker_tasks.append(
                WorkerTask(
                    id=task_id,
                    prompt=prompt,
                    agent_name=None,
                    max_iterations=self.config.worker_max_iterations,
                )
            )
        if not worker_tasks:
            if not self.config.best_effort:
                raise PlanningError("Plan tasks were empty after filtering")
            worker_tasks.append(
                WorkerTask(
                    id="search",
                    prompt=f"Use `web_search` for: {query}. Return key findings with URLs.",
                    max_iterations=self.config.worker_max_iterations,
                )
            )
        return worker_tasks

    def _synthesize_and_render(
        self,
        query: str,
        findings: list[dict[str, Any]],
        citations: list[str],
    ) -> tuple[str, dict[str, Any] | None]:
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

    def _multi_pass_synthesize_and_render(
        self,
        query: str,
        findings: list[dict[str, Any]],
        citations: list[str],
    ) -> tuple[str, dict[str, Any]]:
        allowed_urls = set(citations)

        # 1) Outline
        outline_resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _outline_prompt(query, findings)}],
            temperature=0.2,
            max_tokens=800,
        )
        outline_raw = (outline_resp.choices[0].message.content or "").strip()
        try:
            outline = self._parse_planner_json(outline_raw)
        except Exception as e:
            raise SynthesisError(f"Outline returned invalid JSON: {e}", raw=outline_raw, stage="outline") from e
        sections = outline.get("sections") if isinstance(outline, dict) else None
        if not isinstance(sections, list) or not sections:
            raise SynthesisError("Outline produced no sections", raw=outline_raw, stage="outline")

        # Build evidence per task_id.
        evidence_by_task: dict[str, list[dict[str, Any]]] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            task_id = str(f.get("task_id") or "").strip()
            ev = f.get("evidence")
            if not task_id or not isinstance(ev, list):
                continue
            cleaned = []
            for item in ev:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                excerpt = item.get("excerpt")
                if not (isinstance(url, str) and url in allowed_urls and isinstance(excerpt, str) and excerpt.strip()):
                    continue
                title = item.get("title")
                cleaned.append(
                    {
                        "url": url,
                        "title": title if isinstance(title, str) else "",
                        "excerpt": excerpt.strip(),
                    }
                )
            if cleaned:
                evidence_by_task[task_id] = cleaned

        # 2) Write sections
        all_claims: list[str] = []
        combined_findings_out: list[dict[str, Any]] = []

        for sec in sections[:8]:
            if not isinstance(sec, dict):
                continue
            sec_id = str(sec.get("id") or "").strip()
            sec_title = str(sec.get("title") or "").strip()
            task_ids = sec.get("task_ids") or []
            if not sec_title or not isinstance(task_ids, list) or not task_ids:
                continue
            task_ids = [str(t).strip() for t in task_ids if isinstance(t, str) and str(t).strip()]
            if not task_ids:
                continue

            evidence: list[dict[str, Any]] = []
            for tid in task_ids:
                evidence.extend(evidence_by_task.get(tid, []))
            if not evidence:
                continue

            sec_resp = llm.completion(
                model=self.config.model,
                messages=[{"role": "user", "content": _section_findings_prompt(query, section_title=sec_title, evidence=evidence)}],
                temperature=0.2,
                max_tokens=900,
            )
            sec_raw = (sec_resp.choices[0].message.content or "").strip()
            try:
                sec_payload = self._parse_planner_json(sec_raw)
            except Exception as e:
                raise SynthesisError(
                    f"Section writer returned invalid JSON for '{sec_title}': {e}",
                    raw=sec_raw,
                    stage="section",
                ) from e

            sec_findings = sec_payload.get("findings") if isinstance(sec_payload, dict) else None
            if not isinstance(sec_findings, list) or not sec_findings:
                continue

            # Validate quotes: must come from excerpts we provided.
            excerpt_map = {item["url"]: item.get("excerpt", "") for item in evidence if isinstance(item, dict) and isinstance(item.get("url"), str)}

            def _norm(s: str) -> str:
                return " ".join((s or "").split())

            accepted: list[dict[str, Any]] = []
            for it in sec_findings[:10]:
                if not isinstance(it, dict):
                    continue
                claim = str(it.get("claim") or "").strip()
                ev_items = it.get("evidence") or []
                if not claim or not isinstance(ev_items, list) or not ev_items:
                    continue
                kept = []
                for e in ev_items[:3]:
                    if not isinstance(e, dict):
                        continue
                    url = e.get("url")
                    quote = e.get("quote")
                    if not (isinstance(url, str) and url in allowed_urls and isinstance(quote, str)):
                        continue
                    q = _norm(quote)
                    if not q:
                        continue
                    ex = _norm(str(excerpt_map.get(url) or ""))
                    if q not in ex:
                        continue
                    kept.append({"url": url, "quote": quote.strip()})
                if not kept:
                    continue
                accepted.append({"claim": claim, "evidence": kept})

            if not accepted:
                continue
            combined_findings_out.extend(accepted)
            for it in accepted:
                all_claims.append(it["claim"])

        if not combined_findings_out:
            raise SynthesisError("Multi-pass synthesis produced no supported findings", stage="multi_pass")

        findings_target = max(1, int(self.config.report_findings_target))
        combined_findings_out = _select_diverse_findings(
            combined_findings_out,
            target_findings=findings_target,
            min_unique_urls_target=max(0, int(self.config.report_min_unique_citations_target)),
            min_unique_domains_target=max(0, int(self.config.report_min_unique_domains_target)),
        )
        all_claims = [str(it.get("claim") or "").strip() for it in combined_findings_out if isinstance(it, dict)]
        all_claims = [c for c in all_claims if c]

        # 3) Summarize (title/summary/open questions)
        sum_resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _summary_prompt(query, claims=all_claims)}],
            temperature=0.2,
            max_tokens=500,
        )
        sum_raw = (sum_resp.choices[0].message.content or "").strip()
        try:
            summary_payload = self._parse_planner_json(sum_raw)
        except Exception as e:
            raise SynthesisError(f"Summary returned invalid JSON: {e}", raw=sum_raw, stage="summary") from e
        if not isinstance(summary_payload, dict):
            raise SynthesisError("Summary returned invalid shape", raw=sum_raw, stage="summary")

        # Render using existing renderer by faking payload structure.
        synthesized = {
            "title": summary_payload.get("title") or "Deep Research Report",
            "summary_bullets": summary_payload.get("summary_bullets") or [],
            "findings": combined_findings_out,
            "open_questions": summary_payload.get("open_questions") or [],
        }

        # Reuse existing rendering logic by temporarily substituting payload-derived fields.
        # This keeps citation numbering and source list behavior consistent.
        return (
            self._render_from_payload(
            query=query,
            findings=findings,
            citations=citations,
            payload=synthesized,
            ),
            synthesized,
        )

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
                    "citations": [u for u in (list(r.citations) if r.citations else []) if isinstance(u, str) and u in allowed_urls],
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

        # Selection with per-task minimum and per-domain caps, preserving task diversity.
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

        # Pass 1: satisfy min_per_task where possible.
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

        # Pass 2: fill remaining slots round-robin.
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

    def _collect_citations_from_traces(self, results) -> list[str]:
        urls: set[str] = set()
        for r in results:
            for u in getattr(r, "citations", ()) or ():
                if isinstance(u, str) and u.startswith("http"):
                    urls.add(u)
        return sorted(urls)

    def _collect_evidence_urls(self, results) -> list[str]:
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

    def _format_worker_diagnostics(self, results) -> str:
        lines: list[str] = []
        for r in results:
            lines.append(
                f"- {r.task_id}: success={r.success} web_search_calls={getattr(r, 'web_search_calls', 0)} citations={len(getattr(r, 'citations', ()) or ())} error={r.error or ''}".rstrip()
            )
        return "\n".join(lines) if lines else "(no workers)"

    def _apply_worker_invariants(self, results):
        updated = []
        for r in results:
            if not r.success:
                updated.append(r)
                continue
            if self.config.enable_deep_read and len(getattr(r, "evidence", ()) or ()) < 1:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        sources=getattr(r, "sources", {}) or {},
                        web_search_calls=r.web_search_calls,
                        web_search_trace=getattr(r, "web_search_trace", ()) or (),
                        web_extract_calls=int(getattr(r, "web_extract_calls", 0) or 0),
                        web_extract_trace=getattr(r, "web_extract_trace", ()) or (),
                        evidence=getattr(r, "evidence", ()) or (),
                        iterations=int(getattr(r, "iterations", 0) or 0),
                        duration_ms=getattr(r, "duration_ms", None),
                        success=False,
                        error="Worker collected no extracted evidence (web_extract)",
                    )
                )
                continue
            if len(getattr(r, "citations", ()) or ()) < 1 and not self.config.enable_deep_read:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        sources=getattr(r, "sources", {}) or {},
                        web_search_calls=r.web_search_calls,
                        web_search_trace=getattr(r, "web_search_trace", ()) or (),
                        web_extract_calls=int(getattr(r, "web_extract_calls", 0) or 0),
                        web_extract_trace=getattr(r, "web_extract_trace", ()) or (),
                        evidence=getattr(r, "evidence", ()) or (),
                        iterations=int(getattr(r, "iterations", 0) or 0),
                        duration_ms=getattr(r, "duration_ms", None),
                        success=False,
                        error="Worker collected no citations",
                    )
                )
                continue
            updated.append(r)
        return updated
