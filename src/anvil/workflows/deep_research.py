from __future__ import annotations

"""
Public deep-research module.

The implementation lives in `anvil.workflows.deep_research_workflow` to keep this module small
and make the workflow easier to maintain.
"""

from anvil.workflows.deep_research_workflow import (  # noqa: F401
    DeepResearchConfig,
    DeepResearchOutcome,
    DeepResearchRunError,
    DeepResearchWorkflow,
    PlanningError,
    SynthesisError,
    _select_diverse_findings,
    sanitize_snippet,
)

__all__ = [
    "DeepResearchConfig",
    "DeepResearchOutcome",
    "DeepResearchRunError",
    "DeepResearchWorkflow",
    "PlanningError",
    "SynthesisError",
    "_select_diverse_findings",
    "sanitize_snippet",
]
