from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from common import llm
from common.events import EventEmitter, ProgressEvent
from anvil.subagents.parallel import ParallelWorkerRunner, WorkerTask
from anvil.subagents.task_tool import SubagentRunner


@dataclass(frozen=True, slots=True)
class DeepResearchConfig:
    model: str = "gpt-4o"
    max_workers: int = 5
    worker_max_iterations: int = 6
    worker_timeout_s: float = 120.0
    require_citations: bool = True
    min_total_citations: int = 3


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

Write a concise Markdown report with:
- Summary (5-10 bullets)
- Key findings with citations (link URLs)
- Open questions / risks

Be explicit about uncertainty. Do not invent citations.
"""


_URL_RE = re.compile(r"https?://\\S+")


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

    def run(self, query: str) -> str:
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

        citations = self._collect_citations(results)
        if self.config.require_citations and len(citations) < self.config.min_total_citations:
            details = self._format_worker_diagnostics(results)
            raise RuntimeError(
                "Deep research requires web citations but none (or too few) were collected.\n"
                "Fix: run `uv sync --extra search` and ensure `TAVILY_API_KEY` is set.\n\n"
                f"Diagnostics:\n{details}"
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

        report = self._synthesize(query, findings)
        if citations:
            report = report + "\n\n---\n\n## Sources\n" + "\n".join(f"- {u}" for u in citations)

        if self.emitter is not None:
            self.emitter.emit(ProgressEvent(stage="done", current=1, total=1, message="Done"))

        return report

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

    def _synthesize(self, query: str, findings: list[dict[str, Any]]) -> str:
        resp = llm.completion(
            model=self.config.model,
            messages=[{"role": "user", "content": _synthesis_prompt(query, findings)}],
            temperature=0.2,
            max_tokens=1200,
        )
        return (resp.choices[0].message.content or "").strip()

    def _collect_citations(self, results) -> list[str]:
        urls: set[str] = set()
        for r in results:
            for u in getattr(r, "citations", ()) or ():
                if isinstance(u, str) and u.startswith("http"):
                    urls.add(u)
            for u in _URL_RE.findall(r.output or ""):
                u = u.rstrip(").,]}>\"'")
                if u.startswith("http"):
                    urls.add(u)
        return sorted(urls)

    def _format_worker_diagnostics(self, results) -> str:
        lines: list[str] = []
        for r in results:
            lines.append(
                f"- {r.task_id}: success={r.success} web_search_calls={getattr(r, 'web_search_calls', 0)} citations={len(getattr(r, 'citations', ()) or ())} error={r.error or ''}".rstrip()
            )
        return "\n".join(lines) if lines else "(no workers)"
