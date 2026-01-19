from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from anvil.subagents.parallel import WorkerResult, WorkerTask


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
    max_rounds: int = 3
    max_tasks_total: int = 12
    max_tasks_per_round: int = 6
    verify_tasks_round3: int = 2
    worker_max_attempts: int = 2
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
    rounds: list[dict[str, Any]] | None = None
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

