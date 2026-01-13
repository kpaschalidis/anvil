import json
import logging
import time
from typing import Any

from common import llm
from scout.cost import CostTracker, parse_usage
from scout.models import RawDocument, PainSnippet, ExtractionResult, generate_id, utc_now
from scout.prompts import DEFAULT_EXTRACTION_PROMPT_VERSION, get_extraction_prompt

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    pass


class Extractor:
    def __init__(
        self,
        model: str = "gpt-4o",
        prompt_version: str = DEFAULT_EXTRACTION_PROMPT_VERSION,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        cost_tracker: CostTracker | None = None,
    ):
        self.model = model
        self.prompt_version = prompt_version
        self.prompt_template = get_extraction_prompt(prompt_version)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cost_tracker = cost_tracker

    def extract(
        self,
        doc: RawDocument,
        topic: str,
        knowledge: list[str],
    ) -> ExtractionResult:
        prompt = self._build_prompt(doc, topic, knowledge)

        for attempt in range(self.max_retries):
            try:
                response, usage = llm.completion_with_usage(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=4096,
                )
                if self.cost_tracker:
                    self.cost_tracker.record(kind="extraction", usage=parse_usage(usage))

                content = response.choices[0].message.content
                if not content:
                    raise ExtractionError("Empty response from LLM")

                result = self._parse_response(content, doc.doc_id)
                logger.info(
                    f"Extracted {len(result.snippets)} snippets, "
                    f"{len(result.entities)} entities from {doc.doc_id}"
                )
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"Failed to parse extraction response for {doc.doc_id}")
                    return self._empty_result()

            except Exception as e:
                logger.warning(f"Extraction error on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"Failed to extract from {doc.doc_id}: {e}")
                    return self._empty_result()

        return self._empty_result()

    def _build_prompt(
        self,
        doc: RawDocument,
        topic: str,
        knowledge: list[str],
    ) -> str:
        knowledge_text = "No prior knowledge yet."
        if knowledge:
            recent_knowledge = knowledge[-20:]
            knowledge_text = "\n".join(f"- {k}" for k in recent_knowledge)

        content = doc.raw_text
        if len(content) > 8000:
            content = content[:8000] + "\n\n[Content truncated...]"

        return self.prompt_template.format(
            topic=topic,
            source=doc.source_entity,
            title=doc.title,
            url=doc.url,
            content=content,
            knowledge=knowledge_text,
        )

    def _parse_response(self, content: str, doc_id: str) -> ExtractionResult:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)

        snippets: list[PainSnippet] = []
        for s in data.get("snippets", []):
            try:
                snippet = PainSnippet(
                    snippet_id=generate_id(),
                    doc_id=doc_id,
                    excerpt=s.get("excerpt", ""),
                    pain_statement=s.get("pain_statement", ""),
                    signal_type=self._validate_signal_type(s.get("signal_type", "complaint")),
                    intensity=self._clamp(s.get("intensity", 3), 1, 5),
                    confidence=self._clamp(s.get("confidence", 0.5), 0.0, 1.0),
                    entities=s.get("entities", []),
                    extractor_model=self.model,
                    extractor_prompt_version=self.prompt_version,
                    extracted_at=utc_now(),
                )
                snippets.append(snippet)
            except Exception as e:
                logger.warning(f"Failed to parse snippet: {e}")
                continue

        entities = data.get("entities", [])
        if not isinstance(entities, list):
            entities = []

        follow_up_queries = data.get("follow_up_queries", [])
        if not isinstance(follow_up_queries, list):
            follow_up_queries = []

        novelty = self._clamp(data.get("novelty", 0.5), 0.0, 1.0)

        return ExtractionResult(
            snippets=snippets,
            entities=entities,
            follow_up_queries=follow_up_queries[:5],
            novelty=novelty,
        )

    def _validate_signal_type(self, signal_type: str) -> str:
        valid_types = {
            "complaint", "wish", "workaround", "switch",
            "bug", "pricing", "support", "integration", "workflow"
        }
        signal_type = signal_type.lower().strip()
        if signal_type in valid_types:
            return signal_type
        return "complaint"

    def _clamp(self, value: Any, min_val: float, max_val: float) -> float:
        try:
            return max(min_val, min(max_val, float(value)))
        except (TypeError, ValueError):
            return (min_val + max_val) / 2

    def _empty_result(self) -> ExtractionResult:
        return ExtractionResult(
            snippets=[],
            entities=[],
            follow_up_queries=[],
            novelty=0.5,
        )
