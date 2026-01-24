import json

from scout.models import DocumentRef, Page, RawDocument, SearchTask, utc_now
from scout.services.fetch import FetchConfig, FetchService
from common.events import DocumentEvent


class DummySource:
    name = "dummy"

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        return [
            SearchTask(
                source=self.name,
                source_entity="all",
                mode="search",
                query=queries[0] if queries else topic,
            )
        ]

    def discover(self, topic: str, limit: int = 10):
        return []

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        return Page(
            items=[
                DocumentRef(
                    ref_id=f"{self.name}:1",
                    ref_type="post",
                    source=self.name,
                    source_entity="all",
                    discovered_from_task_id=task.task_id,
                    rank=0,
                    preview="one",
                ),
                DocumentRef(
                    ref_id=f"{self.name}:2",
                    ref_type="post",
                    source=self.name,
                    source_entity="all",
                    discovered_from_task_id=task.task_id,
                    rank=1,
                    preview="two",
                ),
            ],
            exhausted=True,
        )

    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        return RawDocument(
            doc_id=ref.ref_id,
            source=self.name,
            source_entity="all",
            url=f"https://example.com/{ref.ref_id}",
            permalink=f"https://example.com/{ref.ref_id}",
            retrieved_at=utc_now(),
            title=f"title:{ref.ref_id}",
            raw_text=f"text:{ref.ref_id}",
        )


def test_fetch_service_writes_raw_jsonl_and_emits_events(tmp_path):
    events: list[object] = []

    svc = FetchService(
        FetchConfig(
            topic="test topic",
            sources=["dummy"],
            data_dir=str(tmp_path),
            max_documents=10,
        ),
        on_event=events.append,
    )

    result = svc.run(sources=[DummySource()])
    assert result.documents_fetched == 2

    session_dir = tmp_path / result.session_id
    raw_path = session_dir / "raw.jsonl"
    assert raw_path.exists()

    lines = raw_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert {p["doc_id"] for p in payloads} == {"dummy:1", "dummy:2"}

    doc_events = [e for e in events if isinstance(e, DocumentEvent)]
    assert [e.doc_id for e in doc_events] == ["dummy:1", "dummy:2"]

