from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostTotals:
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0
    calls_by_kind: dict[str, int] = field(default_factory=dict)


class CostTracker:
    def __init__(self) -> None:
        self._totals = CostTotals()

    def record(self, *, kind: str, usage: Usage) -> None:
        self._totals.calls += 1
        self._totals.calls_by_kind[kind] = self._totals.calls_by_kind.get(kind, 0) + 1
        self._totals.total_tokens += int(usage.total_tokens or 0)
        self._totals.total_cost_usd += float(usage.cost_usd or 0.0)

    def totals(self) -> CostTotals:
        return self._totals


def parse_usage(data: dict | None) -> Usage:
    data = data or {}
    return Usage(
        prompt_tokens=int(data.get("prompt_tokens") or 0),
        completion_tokens=int(data.get("completion_tokens") or 0),
        total_tokens=int(data.get("total_tokens") or 0),
        cost_usd=float(data.get("cost_usd") or 0.0),
    )

