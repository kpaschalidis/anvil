from dataclasses import dataclass

from scout.models import RawDocument


@dataclass(frozen=True)
class FilterConfig:
    min_content_length: int = 100
    min_score: int = 5
    skip_deleted_authors: bool = True


class ContentFilter:
    def __init__(self, config: FilterConfig):
        self.config = config

    def should_extract(self, doc: RawDocument) -> tuple[bool, str]:
        if self.config.min_content_length and len(doc.raw_text) < self.config.min_content_length:
            return False, "too_short"
        if doc.score is not None and doc.score < self.config.min_score:
            return False, "low_score"
        if self.config.skip_deleted_authors and doc.author == "[deleted]":
            return False, "deleted_author"
        return True, "pass"

