import json

from scout.models import DocumentRef, Page, RawDocument, SearchTask, utc_now
from scout.services.fetch import FetchConfig, FetchService


class DummyCursorSource:
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

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        if not task.cursor:
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
                    )
                ],
                next_cursor="c2",
                exhausted=False,
            )
        return Page(
            items=[
                DocumentRef(
                    ref_id=f"{self.name}:2",
                    ref_type="post",
                    source=self.name,
                    source_entity="all",
                    discovered_from_task_id=task.task_id,
                    rank=0,
                    preview="two",
                )
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


def test_fetch_service_resume_continues_task_queue(tmp_path):
    svc1 = FetchService(
        FetchConfig(
            topic="test topic",
            sources=["dummy"],
            data_dir=str(tmp_path),
            max_documents=1,
            max_task_pages=2,
        )
    )
    result1 = svc1.run(sources=[DummyCursorSource()])
    assert result1.documents_fetched == 1

    session_dir = tmp_path / result1.session_id
    state = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    assert len(state["task_queue"]) == 1

    svc2 = FetchService(
        FetchConfig(
            topic="",
            sources=["dummy"],
            data_dir=str(tmp_path),
            session_id=result1.session_id,
            resume=True,
            max_documents=2,
            max_task_pages=2,
        )
    )
    result2 = svc2.run(sources=[DummyCursorSource()])
    assert result2.session_id == result1.session_id
    assert result2.documents_fetched == 2

    raw_path = session_dir / "raw.jsonl"
    lines = raw_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert {p["doc_id"] for p in payloads} == {"dummy:1", "dummy:2"}

    state2 = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    assert len(state2["task_queue"]) == 0

