from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCallRecord:
    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]
    duration_ms: int | None = None


@dataclass(slots=True)
class SubagentTrace:
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    web_search_calls: int = 0
    web_extract_calls: int = 0
    citations: set[str] = field(default_factory=set)
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    extracted: dict[str, dict[str, Any]] = field(default_factory=dict)
    iterations: int = 0
    duration_ms: int | None = None
