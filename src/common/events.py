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
