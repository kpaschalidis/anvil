from __future__ import annotations

from dataclasses import dataclass

from common.events import EventEmitter, ProgressEvent


@dataclass(slots=True)
class ProgressTracker:
    stage: str
    current: int = 0
    total: int | None = None
    emitter: EventEmitter | None = None

    def advance(self, *, message: str = "", step: int = 1) -> None:
        self.current += step
        if self.emitter is not None:
            self.emitter.emit(
                ProgressEvent(
                    stage=self.stage,
                    current=self.current,
                    total=self.total,
                    message=message,
                )
            )

    def set_total(self, total: int | None) -> None:
        self.total = total

