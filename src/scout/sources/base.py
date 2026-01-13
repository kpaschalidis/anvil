from typing import Protocol, runtime_checkable

from scout.models import SearchTask, Page, DocumentRef, RawDocument, SourceEntity


@runtime_checkable
class Source(Protocol):
    name: str

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        """Convert semantic queries to platform-specific search tasks."""
        ...

    def discover(self, topic: str, limit: int = 10) -> list[SourceEntity]: ...

    def search(self, task: SearchTask) -> Page[DocumentRef]: ...

    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument: ...
