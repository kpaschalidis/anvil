from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from common import llm
from common.events import EventEmitter, ProgressEvent
from anvil.subagents.parallel import ParallelWorkerRunner, WorkerTask
from anvil.subagents.task_tool import SubagentRunner
from anvil.subagents.parallel import WorkerResult


@dataclass(frozen=True, slots=True)
class DeepResearchConfig:
    model: str = "gpt-4o"
    max_workers: int = 5
    worker_max_iterations: int = 6
    worker_timeout_s: float = 120.0
    require_citations: bool = True
    min_total_citations: int = 3
    strict_all: bool = False
    best_effort: bool = False


@dataclass(frozen=True, slots=True)
class DeepResearchOutcome:
    query: str
    plan: dict[str, Any]
    tasks: list[WorkerTask]
    results: list[WorkerResult]
    citations: list[str]
    report_markdown: str


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

        plan = self._plan(query)
        tasks = self._to_worker_tasks(plan)

        if self.emitter is not None:
            self.emitter.emit(
                ProgressEvent(
                    stage="workers",
                    current=0,
                    total=len(tasks),
                    message=f"Running {len(tasks)} workers",
                )
            )

        results = self.parallel_runner.spawn_parallel(
            tasks,
            max_workers=self.config.max_workers,
            timeout=self.config.worker_timeout_s,
            allow_writes=False,
        )

        results = self._apply_worker_invariants(results)
        citations = self._collect_citations_from_traces(results)
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

        findings: list[dict[str, Any]] = []
        for r in results:
            findings.append(
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "citations": list(r.citations),
                    "web_search_calls": int(r.web_search_calls or 0),
                }
            )

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="synthesize", current=0, total=None, message="Synthesizing report"))

        report = self._synthesize_and_render(query, findings, citations)

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="done", current=1, total=1, message="Done"))

        return DeepResearchOutcome(
            query=query,
            plan=plan,
            tasks=tasks,
            results=results,
            citations=citations,
            report_markdown=report,
        )

    def _plan(self, query: str) -> dict[str, Any]:
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _planning_prompt(query, max_tasks=5)}],
            temperature=0.2,
            max_tokens=800,
        )
        content = resp.choices[0].message.content or ""
        try:
            return json.loads(content)
        except Exception:
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

    def _to_worker_tasks(self, plan: dict[str, Any]) -> list[WorkerTask]:
        tasks = plan.get("tasks") if isinstance(plan, dict) else None
        if not isinstance(tasks, list) or not tasks:
            tasks = []
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
                "You MUST call `web_search` at least once. Prefer 2-3 calls with different queries/pages.\n\n"
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
        rendered_findings: list[str] = []
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
                rendered_findings.append(
                    f"- {claim} " + " ".join(f"[source]({u})" for u in cites[:3])
                )

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

        if citations:
            lines.append("## Sources")
            lines.extend(f"- {u}" for u in citations)
            lines.append("")

        return "\n".join(lines).strip()

    def _collect_citations_from_traces(self, results) -> list[str]:
        urls: set[str] = set()
        for r in results:
            for u in getattr(r, "citations", ()) or ():
                if isinstance(u, str) and u.startswith("http"):
                    urls.add(u)
        return sorted(urls)

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
            if int(getattr(r, "web_search_calls", 0) or 0) < 1:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        web_search_calls=r.web_search_calls,
                        success=False,
                        error="Worker did not call web_search",
                    )
                )
                continue
            if len(getattr(r, "citations", ()) or ()) < 1:
                updated.append(
                    WorkerResult(
                        task_id=r.task_id,
                        output=r.output,
                        citations=r.citations,
                        web_search_calls=r.web_search_calls,
                        success=False,
                        error="Worker collected no citations",
                    )
                )
                continue
            updated.append(r)
        return updated
