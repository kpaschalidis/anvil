from __future__ import annotations

import json
from typing import Any

from common import llm
from common.events import ProgressEvent

from anvil.subagents.parallel import WorkerTask
from anvil.workflows.deep_research_prompts import (
    _gap_fill_prompt_from_memo,
    _planning_prompt,
    _verification_prompt_from_memo,
)
from anvil.workflows.deep_research_types import PlanningError
from anvil.workflows.iterative_loop import ReportType, ResearchMemo, detect_report_type


class DeepResearchPlanningMixin:
    def _plan(
        self,
        query: str,
        *,
        max_tasks: int,
        min_tasks: int,
        report_type: ReportType = ReportType.NARRATIVE,
    ) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": _planning_prompt(
                        query,
                        max_tasks=max(1, int(max_tasks)),
                        report_type=report_type,
                    ),
                }
            ],
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

    def _gap_fill_plan(
        self,
        query: str,
        memo: ResearchMemo,
        *,
        max_tasks: int,
    ) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": _gap_fill_prompt_from_memo(
                        query,
                        memo,
                        max_tasks=max(0, int(max_tasks)),
                    ),
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
        # Accept both the legacy shape {"tasks":[...]} and the new shape {"gaps":[...],"tasks":[...]}.
        validated = self._validate_plan(plan, min_tasks=0)
        tasks = validated.get("tasks") or []
        # Prefix task IDs to avoid collisions with round 1.
        for t in tasks:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and not t["id"].startswith("r2_"):
                t["id"] = f"r2_{t['id']}"
        return {"tasks": tasks[: max(0, int(max_tasks))]}, content, None

    def _verification_plan(
        self,
        query: str,
        memo: ResearchMemo,
        *,
        max_tasks: int,
        min_tasks: int = 0,
    ) -> tuple[dict[str, Any], str, str | None]:
        resp = llm.completion(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": _verification_prompt_from_memo(
                        query,
                        memo,
                        max_tasks=max(0, int(max_tasks)),
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
        validated = self._validate_plan(plan, min_tasks=max(0, int(min_tasks)))
        tasks = validated.get("tasks") or []
        for t in tasks:
            if isinstance(t, dict) and isinstance(t.get("id"), str) and not str(t["id"]).startswith("v_"):
                t["id"] = f"v_{t['id']}"
        return {"tasks": tasks[: max(0, int(max_tasks))]}, content, None

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
                }
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
        report_type = detect_report_type(query)
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
            if report_type == ReportType.CATALOG:
                prompt = (
                    "You are collecting candidates for a structured catalog.\n"
                    "Use the `web_search` tool to find provider sites, pricing pages, and case studies.\n"
                    f"Aim for ~{max(1, int(self.config.target_web_search_calls))} `web_search` calls.\n"
                    f"Use pagination (page=1..{max(1, int(self.config.max_pages))}) and page_size={max(1, int(self.config.page_size))}.\n"
                    f"{read_block}"
                    "Stop searching once you have enough evidence.\n\n"
                    f"Search query: {search_query}\n\n"
                    f"Instructions: {instructions}\n\n"
                    "Return ONLY valid JSON (no markdown, no code fences) in this exact shape:\n"
                    "{\n"
                    '  "candidates": [\n'
                    "    {\n"
                    '      "name": "string",\n'
                    '      "provider": "string",\n'
                    '      "website_url": "https://...",\n'
                    '      "problem_solved": "string",\n'
                    '      "who_its_for": "string",\n'
                    '      "how_ai_is_used": "string",\n'
                    '      "pricing_model": "string",\n'
                    '      "why_evergreen": "string",\n'
                    '      "replicable_with": "string",\n'
                    '      "proof_links": ["https://..."]\n'
                    "    }\n"
                    "  ]\n"
                    "}\n"
                )
            else:
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
