import pytest
import tempfile
import shutil
from pathlib import Path

from scout.storage import Storage, atomic_write_json, load_json
from scout.models import RawDocument, PainSnippet, Event


class TestStorage:
    @pytest.fixture
    def temp_dir(self):
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp)

    @pytest.fixture
    def storage(self, temp_dir):
        return Storage("test_session", temp_dir)

    def test_init_creates_directory(self, storage, temp_dir):
        session_dir = Path(temp_dir) / "test_session"
        assert session_dir.exists()
        assert (session_dir / "session.db").exists()

    def test_save_and_get_document(self, storage):
        doc = RawDocument(
            doc_id="reddit:t3_test123",
            source="reddit",
            source_entity="r/test",
            url="https://reddit.com/r/test/123",
            permalink="/r/test/comments/123",
            title="Test Post",
            raw_text="Test content here",
            author="testuser",
            score=100,
            num_comments=50,
        )
        storage.save_document(doc)

        retrieved = storage.get_document(doc.doc_id)
        assert retrieved is not None
        assert retrieved.doc_id == doc.doc_id
        assert retrieved.title == "Test Post"
        assert retrieved.author == "testuser"

    def test_document_exists(self, storage):
        assert not storage.document_exists("nonexistent")

        doc = RawDocument(
            doc_id="reddit:t3_exists",
            source="reddit",
            source_entity="r/test",
            url="https://reddit.com/r/test/exists",
            permalink="/r/test/comments/exists",
            title="Exists",
            raw_text="Content",
        )
        storage.save_document(doc)

        assert storage.document_exists("reddit:t3_exists")

    def test_save_and_get_snippet(self, storage):
        doc = RawDocument(
            doc_id="reddit:t3_fordoc",
            source="reddit",
            source_entity="r/test",
            url="https://reddit.com/r/test/fordoc",
            permalink="/r/test/comments/fordoc",
            title="For Doc",
            raw_text="Content",
        )
        storage.save_document(doc)

        snippet = PainSnippet(
            snippet_id="snip123",
            doc_id=doc.doc_id,
            excerpt="I hate this",
            pain_statement="Product is frustrating",
            signal_type="complaint",
            intensity=4,
            confidence=0.85,
            entities=["ProductX"],
            extractor_model="gpt-4o",
            extractor_prompt_version="v1",
        )
        storage.save_snippet(snippet)

        snippets = storage.get_snippets_for_document(doc.doc_id)
        assert len(snippets) == 1
        assert snippets[0].snippet_id == "snip123"
        assert snippets[0].pain_statement == "Product is frustrating"

    def test_get_document_count(self, storage):
        assert storage.get_document_count() == 0

        for i in range(3):
            doc = RawDocument(
                doc_id=f"reddit:t3_count{i}",
                source="reddit",
                source_entity="r/test",
                url=f"https://reddit.com/{i}",
                permalink=f"/r/test/{i}",
                title=f"Doc {i}",
                raw_text="Content",
            )
            storage.save_document(doc)

        assert storage.get_document_count() == 3

    def test_log_event(self, storage, temp_dir):
        event = Event(
            session_id="test_session",
            kind="task_started",
            input={"task_id": "t1"},
            decision="Starting task",
        )
        storage.log_event(event)

        events_file = Path(temp_dir) / "test_session" / "events.jsonl"
        assert events_file.exists()


class TestAtomicWriteJson:
    @pytest.fixture
    def temp_dir(self):
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)

    def test_atomic_write(self, temp_dir):
        filepath = temp_dir / "test.json"
        data = {"key": "value", "number": 42}

        atomic_write_json(filepath, data)

        assert filepath.exists()
        loaded = load_json(filepath)
        assert loaded == data

    def test_atomic_write_creates_parent(self, temp_dir):
        filepath = temp_dir / "nested" / "dir" / "test.json"
        data = {"nested": True}

        atomic_write_json(filepath, data)

        assert filepath.exists()

    def test_load_json_missing_file(self, temp_dir):
        result = load_json(temp_dir / "nonexistent.json")
        assert result is None
