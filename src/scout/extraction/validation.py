from dataclasses import dataclass

from scout.models import PainSnippet


@dataclass(frozen=True)
class SnippetValidationConfig:
    min_confidence: float = 0.0
    min_excerpt_length: int = 10
    min_pain_statement_length: int = 10


class SnippetValidator:
    def __init__(self, config: SnippetValidationConfig):
        self.config = config

    def validate(self, snippets: list[PainSnippet]) -> tuple[list[PainSnippet], int]:
        seen: set[str] = set()
        kept: list[PainSnippet] = []
        dropped = 0

        for s in snippets:
            excerpt = (s.excerpt or "").strip()
            pain = (s.pain_statement or "").strip()

            if len(excerpt) < self.config.min_excerpt_length:
                dropped += 1
                continue
            if len(pain) < self.config.min_pain_statement_length:
                dropped += 1
                continue
            if s.confidence < self.config.min_confidence:
                dropped += 1
                continue

            key = pain.lower()
            if key in seen:
                dropped += 1
                continue
            seen.add(key)

            kept.append(s.model_copy(update={"excerpt": excerpt, "pain_statement": pain}))

        return kept, dropped

