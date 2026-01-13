from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressInfo:
    iteration: int
    max_iterations: int
    docs_collected: int
    max_documents: int
    snippets_extracted: int
    tasks_remaining: int
    avg_novelty: float
    total_cost_usd: float
