from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from anvil.subagents.task_tool import SubagentRunner
from anvil.subagents.trace import ToolCallRecord


WORKER_SAFE_TOOLS: set[str] = {"read_file", "grep", "list_files", "web_search", "web_extract"}


@dataclass(frozen=True, slots=True)
class WorkerTask:
    id: str
    prompt: str
    agent_name: str | None = None
    max_iterations: int = 6
    max_web_search_calls: int | None = None
    max_web_extract_calls: int | None = None


@dataclass(frozen=True, slots=True)
class WorkerResult:
    task_id: str
    output: str = ""
    citations: tuple[str, ...] = ()
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    web_search_calls: int = 0
    web_search_trace: tuple[dict[str, Any], ...] = ()
    web_extract_calls: int = 0
    web_extract_trace: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    iterations: int = 0
    duration_ms: int | None = None
    success: bool = True
    error: str | None = None


def _summarize_web_search_calls(tool_calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in tool_calls:
        if getattr(rec, "tool_name", None) != "web_search":
            continue
        result = getattr(rec, "result", None)
        if not isinstance(result, dict) or result.get("success") is not True:
            out.append(
                {
                    "success": False,
                    "error": (result or {}).get("error") if isinstance(result, dict) else None,
                    "duration_ms": getattr(rec, "duration_ms", None),
                }
            )
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        items = payload.get("results")
        if not isinstance(items, list):
            items = []
        urls: list[str] = []
        results: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            u = it.get("url")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
                entry: dict[str, Any] = {"url": u}
                title = it.get("title")
                if isinstance(title, str) and title.strip():
                    entry["title"] = title.strip()
                score = it.get("score")
                if isinstance(score, (int, float)):
                    entry["score"] = float(score)
                snippet = it.get("content") or it.get("snippet") or it.get("description")
                if isinstance(snippet, str) and snippet.strip():
                    entry["snippet"] = snippet.strip()[:500]
                results.append(entry)
        out.append(
            {
                "success": True,
                "query": payload.get("query"),
                "page": payload.get("page"),
                "page_size": payload.get("page_size"),
                "has_more": payload.get("has_more"),
                "result_count": len(items),
                "urls": urls,
                "results": results,
                "duration_ms": getattr(rec, "duration_ms", None),
            }
        )
    return out


def _summarize_web_extract_calls(tool_calls: list[ToolCallRecord]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for rec in tool_calls:
        if getattr(rec, "tool_name", None) != "web_extract":
            continue
        args = getattr(rec, "args", None)
        requested_url = args.get("url") if isinstance(args, dict) else None
        result = getattr(rec, "result", None)
        if not isinstance(result, dict) or result.get("success") is not True:
            trace.append(
                {
                    "success": False,
                    "url": requested_url,
                    "error": (result or {}).get("error") if isinstance(result, dict) else None,
                    "duration_ms": getattr(rec, "duration_ms", None),
                }
            )
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        url = payload.get("url") or requested_url
        raw = payload.get("raw_content")
        if not isinstance(url, str):
            continue
        if not isinstance(raw, str):
            raw = ""
        title = payload.get("title")
        if not isinstance(title, str):
            title = ""
        ev = {
            "url": url,
            "title": title.strip(),
            "excerpt": raw[:1500],
            "sha256": payload.get("sha256") or "",
            "raw_len": int(payload.get("raw_len") or 0),
            "truncated": bool(payload.get("truncated") is True),
        }
        evidence.append(ev)
        trace.append(
            {
                "success": True,
                "url": url,
                "raw_len": ev["raw_len"],
                "truncated": ev["truncated"],
                "duration_ms": getattr(rec, "duration_ms", None),
            }
        )
    return trace, evidence


def _select_urls_for_extract(
    *,
    candidates: list[str],
    sources: dict[str, dict[str, str]],
    max_urls: int,
) -> list[str]:
    max_urls = max(0, int(max_urls))
    if max_urls <= 0:
        return []

    def _domain(u: str) -> str:
        try:
            return urlparse(u).netloc.lower().strip()
        except Exception:
            return ""

    ordered: list[str] = []
    seen_url: set[str] = set()
    seen_domain: set[str] = set()

    # Prefer URLs that already have metadata (title/snippet) in Tavily results.
    prioritized = [u for u in candidates if u in sources] + [u for u in candidates if u not in sources]
    for u in prioritized:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        if u in seen_url:
            continue
        d = _domain(u)
        if d and d in seen_domain:
            continue
        ordered.append(u)
        seen_url.add(u)
        if d:
            seen_domain.add(d)
        if len(ordered) >= max_urls:
            break
    return ordered


class ParallelWorkerRunner:
    def __init__(self, runner: SubagentRunner):
        self.runner = runner

    def spawn_parallel(
        self,
        tasks: list[WorkerTask],
        *,
        max_workers: int = 5,
        timeout: float | None = 60.0,
        allow_writes: bool = False,
        max_web_search_calls: int | None = None,
        max_web_extract_calls: int | None = None,
        extract_max_chars: int = 20_000,
        on_result=None,
    ) -> list[WorkerResult]:
        if not tasks:
            return []

        allowed_tool_names = None if allow_writes else WORKER_SAFE_TOOLS

        results: list[WorkerResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.runner.run_task_with_trace,
                    prompt=task.prompt,
                    agent_name=task.agent_name,
                    max_iterations=task.max_iterations,
                    **self._run_kwargs(
                        allowed_tool_names=allowed_tool_names,
                        max_web_search_calls=(
                            task.max_web_search_calls
                            if task.max_web_search_calls is not None
                            else max_web_search_calls
                        ),
                        max_web_extract_calls=(
                            task.max_web_extract_calls
                            if task.max_web_extract_calls is not None
                            else max_web_extract_calls
                        ),
                    ),
                ): task
                for task in tasks
            }

            for future in as_completed(futures, timeout=timeout):
                task = futures[future]
                try:
                    output, trace = future.result()

                    # If the model didn't call `web_extract` but we have budget for deep read,
                    # do a deterministic extract pass on top URLs to ensure evidence exists.
                    budget_extract = (
                        task.max_web_extract_calls
                        if task.max_web_extract_calls is not None
                        else max_web_extract_calls
                    )
                    tool_registry = getattr(self.runner, "tool_registry", None)
                    if (
                        isinstance(budget_extract, int)
                        and budget_extract > 0
                        and int(getattr(trace, "web_extract_calls", 0) or 0) < 1
                        and tool_registry is not None
                        and hasattr(tool_registry, "execute_tool")
                    ):
                        citations = sorted(getattr(trace, "citations", set()) or set())
                        sources = dict(getattr(trace, "sources", {}) or {})
                        selected = _select_urls_for_extract(
                            candidates=citations,
                            sources=sources,
                            max_urls=budget_extract,
                        )
                        for url in selected:
                            # execute_tool returns {"success": bool, "result": payload | ...}
                            result = tool_registry.execute_tool(
                                "web_extract",
                                {"url": url, "max_chars": int(extract_max_chars)},
                            )
                            trace.tool_calls.append(
                                ToolCallRecord(
                                    tool_name="web_extract",
                                    args={"url": url, "max_chars": int(extract_max_chars)},
                                    result=result,
                                    duration_ms=None,
                                )
                            )
                            if hasattr(trace, "web_extract_calls"):
                                trace.web_extract_calls += 1
                            if hasattr(trace, "extracted") and isinstance(result, dict) and result.get("success") is True:
                                payload = result.get("result")
                                if isinstance(payload, dict) and isinstance(payload.get("url"), str):
                                    trace.extracted[payload["url"]] = payload

                    ws_trace = _summarize_web_search_calls(getattr(trace, "tool_calls", []) or [])
                    we_trace, evidence = _summarize_web_extract_calls(getattr(trace, "tool_calls", []) or [])
                    results.append(
                        WorkerResult(
                            task_id=task.id,
                            output=output or "",
                            citations=tuple(sorted(getattr(trace, "citations", set()) or set())),
                            sources=dict(getattr(trace, "sources", {}) or {}),
                            web_search_calls=int(getattr(trace, "web_search_calls", 0) or 0),
                            web_search_trace=tuple(ws_trace),
                            web_extract_calls=int(getattr(trace, "web_extract_calls", 0) or 0),
                            web_extract_trace=tuple(we_trace),
                            evidence=tuple(evidence),
                            iterations=int(getattr(trace, "iterations", 0) or 0),
                            duration_ms=getattr(trace, "duration_ms", None),
                            success=True,
                        )
                    )
                    if on_result is not None:
                        on_result(results[-1])
                except Exception as e:
                    results.append(WorkerResult(task_id=task.id, success=False, error=str(e)))
                    if on_result is not None:
                        on_result(results[-1])

        return results

    @staticmethod
    def _run_kwargs(
        *,
        allowed_tool_names: set[str] | None,
        max_web_search_calls: int | None,
        max_web_extract_calls: int | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"allowed_tool_names": allowed_tool_names}
        if max_web_search_calls is not None:
            kwargs["max_web_search_calls"] = max_web_search_calls
        if max_web_extract_calls is not None:
            kwargs["max_web_extract_calls"] = max_web_extract_calls
        return kwargs
