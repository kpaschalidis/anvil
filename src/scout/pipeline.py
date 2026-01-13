from dataclasses import dataclass

from scout.extract import Extractor
from scout.filters import ContentFilter
from scout.models import ExtractionResult, RawDocument


@dataclass(frozen=True)
class PipelineResult:
    filtered: bool
    reason: str
    extraction: ExtractionResult | None = None


class ExtractionPipeline:
    def __init__(self, *, content_filter: ContentFilter, extractor: Extractor):
        self.content_filter = content_filter
        self.extractor = extractor

    def process(self, doc: RawDocument, *, topic: str, knowledge: list[str]) -> PipelineResult:
        should_extract, reason = self.content_filter.should_extract(doc)
        if not should_extract:
            return PipelineResult(filtered=True, reason=reason, extraction=None)

        extraction = self.extractor.extract(doc, topic, knowledge)
        return PipelineResult(filtered=False, reason="extracted", extraction=extraction)

