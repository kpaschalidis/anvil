from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeAlias


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: str
    current: int
    total: int | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class ResearchPlanEvent:
    tasks: list[dict]


@dataclass(frozen=True, slots=True)
class WorkerCompletedEvent:
    task_id: str
    success: bool
    web_search_calls: int = 0
    web_extract_calls: int = 0
    citations: int = 0
    domains: int = 0
    evidence: int = 0
    duration_ms: int | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class AssistantResponseStartEvent:
    iteration: int


@dataclass(frozen=True, slots=True)
class AssistantDeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantMessageEvent:
    content: str


@dataclass(frozen=True, slots=True)
class DocumentEvent:
    doc_id: str
    title: str
    source: str


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    tool_call_id: str
    tool_name: str
    args: dict


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    tool_call_id: str
    tool_name: str
    result: dict


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str
    source: str | None = None


Event: TypeAlias = (
    ProgressEvent
    | ResearchPlanEvent
    | WorkerCompletedEvent
    | AssistantResponseStartEvent
    | AssistantDeltaEvent
    | AssistantMessageEvent
    | DocumentEvent
    | ToolCallEvent
    | ToolResultEvent
    | ErrorEvent
)
EventCallback: TypeAlias = Callable[[Event], None] | None


class EventEmitter:
    def __init__(self, callback: EventCallback = None):
        self._callback = callback

    def emit(self, event: Event) -> None:
        if self._callback is not None:
            self._callback(event)
