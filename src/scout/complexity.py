import logging
from enum import Enum

from common import llm
from scout.cost import CostTracker, parse_usage

logger = logging.getLogger(__name__)


class TopicComplexity(Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


ITERATION_BUDGETS = {
    TopicComplexity.SIMPLE: 30,
    TopicComplexity.MEDIUM: 60,
    TopicComplexity.COMPLEX: 100,
}

COMPLEXITY_PROMPT = '''Assess the research complexity of this topic:

Topic: "{topic}"

Complexity levels:
- SIMPLE: Single product, specific tool, narrow niche (e.g., "HawkSoft AMS problems", "Notion calendar bugs")
- MEDIUM: Industry segment, multiple products, defined scope (e.g., "insurance broker software", "project management tools for agencies")
- COMPLEX: Broad market, many dimensions, open-ended (e.g., "small business pain points", "SaaS pricing problems")

Respond with exactly one word: SIMPLE, MEDIUM, or COMPLEX'''


def assess_complexity(
    topic: str,
    model: str = "gpt-4o-mini",
    *,
    cost_tracker: CostTracker | None = None,
) -> TopicComplexity:
    try:
        response, usage = llm.completion_with_usage(
            model=model,
            messages=[{"role": "user", "content": COMPLEXITY_PROMPT.format(topic=topic)}],
            temperature=0.0,
            max_tokens=10,
        )
        if cost_tracker:
            cost_tracker.record(kind="complexity", usage=parse_usage(usage))

        result = response.choices[0].message.content.strip().upper()

        if result == "SIMPLE":
            complexity = TopicComplexity.SIMPLE
        elif result == "COMPLEX":
            complexity = TopicComplexity.COMPLEX
        else:
            complexity = TopicComplexity.MEDIUM

        logger.info(f"Topic '{topic}' assessed as {complexity.value}")
        return complexity

    except Exception as e:
        logger.warning(f"Failed to assess complexity: {e}, defaulting to MEDIUM")
        return TopicComplexity.MEDIUM


def get_iteration_budget(
    topic: str,
    model: str = "gpt-4o-mini",
    *,
    cost_tracker: CostTracker | None = None,
) -> int:
    complexity = assess_complexity(topic, model, cost_tracker=cost_tracker)
    budget = ITERATION_BUDGETS[complexity]
    logger.info(f"Iteration budget for '{topic}': {budget}")
    return budget
