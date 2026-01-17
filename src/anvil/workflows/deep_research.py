from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from common import llm
from common.events import EventEmitter, ProgressEvent
from anvil.subagents.parallel import ParallelWorkerRunner, WorkerTask
from anvil.subagents.task_tool import SubagentRunner
from anvil.subagents.parallel import WorkerResult


class PlanningError(RuntimeError):
    def __init__(self, message: str, *, raw: str = ""):
        super().__init__(message)
        self.raw = raw


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
    enable_round2: bool = False
    round2_max_tasks: int = 3
    require_citations: bool = True
    min_total_citations: int = 3
    strict_all: bool = True
    best_effort: bool = False


@dataclass(frozen=True, slots=True)
class DeepResearchOutcome:
    query: str
    plan: dict[str, Any]
    tasks: list[WorkerTask]
    results: list[WorkerResult]
    citations: list[str]
    report_markdown: str
    planner_raw: str = ""
    planner_error: str | None = None
    gap_plan: dict[str, Any] | None = None
    gap_planner_raw: str = ""
    gap_planner_error: str | None = None


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


def _synthesis_prompt(query: str, findings: list[dict[str, Any]]) -> str:
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
    {{
      "claim": "string",
      "citations": ["https://..."]
    }}
  ],
  "open_questions": ["string"]
}}

Rules:
- Every item in `findings[].citations` MUST be a URL present in the worker findings citations.
- Base claims only on information supported by the cited sources (use source titles/snippets in the worker findings).
- If you cannot support a claim with citations, omit it.
- Be explicit about uncertainty.
"""


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
        )

        results = self._apply_worker_invariants(results)
        citations = self._collect_citations_from_traces(results)
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
                    "web_search_calls": int(r.web_search_calls or 0),
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
                )
                more = self._apply_worker_invariants(more)
                results = list(results) + list(more)
                citations = self._collect_citations_from_traces(results)
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
                            "web_search_calls": int(r.web_search_calls or 0),
                        }
                    )

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="synthesize", current=0, total=None, message="Synthesizing report"))

        report = self._synthesize_and_render(query, findings, citations)

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="done", current=1, total=1, message="Done"))

        combined_plan = plan
        if round2_tasks:
            combined_plan = {"tasks": (plan.get("tasks") or []) + (gap_plan.get("tasks") or [])} if gap_plan else plan

        return DeepResearchOutcome(
            query=query,
            plan=combined_plan,
            planner_raw=planner_raw,
            planner_error=planner_error,
            tasks=round1_tasks + round2_tasks,
            results=results,
            citations=citations,
            report_markdown=report,
            gap_plan=gap_plan,
            gap_planner_raw=gap_planner_raw,
            gap_planner_error=gap_planner_error,
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
            prompt = (
                "Use the `web_search` tool to gather sources and extract key facts.\n"
                f"Aim for ~{max(1, int(self.config.target_web_search_calls))} `web_search` calls.\n"
                f"Use pagination (page=1..{max(1, int(self.config.max_pages))}) and page_size={max(1, int(self.config.page_size))}.\n"
                f"Aim for 2+ distinct query variants (refine queries as you learn).\n"
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
    ) -> str:
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _synthesis_prompt(query, findings)}],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = (resp.choices[0].message.content or "").strip()
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(raw)
        except Exception:
            if not self.config.best_effort:
                raise RuntimeError("Synthesis returned invalid JSON")

        title = str((payload or {}).get("title") or "Deep Research Report")
        summary = (payload or {}).get("summary_bullets") or []
        findings_out = (payload or {}).get("findings") or []
        open_qs = (payload or {}).get("open_questions") or []

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
                        title = meta.get("title")
                        snippet = meta.get("snippet")
                        if isinstance(title, str) and title.strip():
                            merged["title"] = title.strip()
                        if isinstance(snippet, str) and snippet.strip():
                            merged["snippet"] = snippet.strip()
                        if merged:
                            source_meta.setdefault(url, {}).update(merged)

        rendered_findings: list[str] = []
        citation_numbers: dict[str, int] = {}
        ordered_urls: list[str] = []

        def _num(url: str) -> int:
            if url not in citation_numbers:
                citation_numbers[url] = len(citation_numbers) + 1
                ordered_urls.append(url)
            return citation_numbers[url]

        def _why(url: str) -> str:
            meta = source_meta.get(url) or {}
            snippet = (meta.get("snippet") or "").strip()
            title = (meta.get("title") or "").strip()
            if snippet:
                s = " ".join(snippet.split())
                return s[:220] + ("…" if len(s) > 220 else "")
            if title:
                return title
            return url.split("/")[2] if url.startswith("http") else url

        if isinstance(findings_out, list):
            for it in findings_out:
                if not isinstance(it, dict):
                    continue
                claim = str(it.get("claim") or "").strip()
                cites = it.get("citations") or []
                if not claim:
                    continue
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

        if self.config.require_citations and not self.config.best_effort and not rendered_findings:
            raise RuntimeError("Synthesis produced no cited findings")

        lines: list[str] = [f"# {title}", ""]
        if self.config.best_effort:
            lines.extend(
                [
                    "> Warning: best-effort mode enabled; output may be incomplete.",
                    "",
                ]
            )

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
                title = (meta.get("title") or "").strip()
                label = f"{title} — {u}" if title else u
                lines.append(f"- [{n}]({u}) {label}")
            lines.append("")

        return "\n".join(lines).strip()

    def _collect_citations_from_traces(self, results) -> list[str]:
        urls: set[str] = set()
        for r in results:
            for u in getattr(r, "citations", ()) or ():
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
            if len(getattr(r, "citations", ()) or ()) < 1:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        sources=getattr(r, "sources", {}) or {},
                        web_search_calls=r.web_search_calls,
                        success=False,
                        error="Worker collected no citations",
                    )
                )
                continue
            updated.append(r)
        return updated
