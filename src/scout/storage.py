import json
import sqlite3
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Iterator

from scout.models import RawDocument, PainSnippet, Event

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_entity TEXT NOT NULL,
    url TEXT NOT NULL,
    permalink TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    published_at TEXT,
    title TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    author TEXT,
    score INTEGER,
    num_comments INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS snippets (
    snippet_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    excerpt TEXT NOT NULL,
    pain_statement TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    intensity INTEGER NOT NULL,
    confidence REAL NOT NULL,
    entities TEXT NOT NULL DEFAULT '[]',
    extractor_model TEXT NOT NULL,
    extractor_prompt_version TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_snippets_doc_id ON snippets(doc_id);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_snippets_signal_type ON snippets(signal_type);
"""


class Storage:
    def __init__(self, session_id: str, data_dir: str = "data/sessions"):
        self.session_id = session_id
        self.session_dir = Path(data_dir) / session_id
        self.db_path = self.session_dir / "session.db"
        self._conn: sqlite3.Connection | None = None
        self._ensure_directory()
        self._init_db()

    def _ensure_directory(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Session directory ensured: {self.session_dir}")

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        
        cursor = self._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        if not cursor.fetchone():
            cursor.executescript(SCHEMA)
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()
            logger.info(f"Database initialized with schema version {SCHEMA_VERSION}")
        else:
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            if row and row[0] != SCHEMA_VERSION:
                logger.warning(f"Schema version mismatch: expected {SCHEMA_VERSION}, got {row[0]}")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("Database connection not initialized")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def save_document(self, doc: RawDocument) -> None:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO documents 
                (doc_id, source, source_entity, url, permalink, retrieved_at, 
                 published_at, title, raw_text, author, score, num_comments, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.doc_id,
                    doc.source,
                    doc.source_entity,
                    doc.url,
                    doc.permalink,
                    doc.retrieved_at.isoformat(),
                    doc.published_at.isoformat() if doc.published_at else None,
                    doc.title,
                    doc.raw_text,
                    doc.author,
                    doc.score,
                    doc.num_comments,
                    json.dumps(doc.metadata),
                ),
            )
            self.conn.commit()
            self._append_jsonl("raw.jsonl", doc.model_dump(mode="json"))
            logger.debug(f"Saved document {doc.doc_id}")
        except sqlite3.Error as e:
            logger.error(f"Failed to save document {doc.doc_id}: {e}")
            raise StorageError(f"Failed to save document: {e}") from e

    def save_snippet(self, snippet: PainSnippet) -> None:
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO snippets 
                (snippet_id, doc_id, excerpt, pain_statement, signal_type, intensity,
                 confidence, entities, extractor_model, extractor_prompt_version, 
                 extracted_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snippet.snippet_id,
                    snippet.doc_id,
                    snippet.excerpt,
                    snippet.pain_statement,
                    snippet.signal_type,
                    snippet.intensity,
                    snippet.confidence,
                    json.dumps(snippet.entities),
                    snippet.extractor_model,
                    snippet.extractor_prompt_version,
                    snippet.extracted_at.isoformat(),
                    json.dumps(snippet.metadata),
                ),
            )
            self.conn.commit()
            self._append_jsonl("snippets.jsonl", snippet.model_dump(mode="json"))
            logger.debug(f"Saved snippet {snippet.snippet_id}")
        except sqlite3.Error as e:
            logger.error(f"Failed to save snippet {snippet.snippet_id}: {e}")
            raise StorageError(f"Failed to save snippet: {e}") from e

    def log_event(self, event: Event) -> None:
        self._append_jsonl("events.jsonl", event.model_dump(mode="json"))
        logger.debug(f"Logged event {event.kind}: {event.event_id}")

    def _append_jsonl(self, filename: str, data: dict) -> None:
        filepath = self.session_dir / filename
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, default=str) + "\n")
        except IOError as e:
            logger.error(f"Failed to append to {filename}: {e}")
            raise StorageError(f"Failed to append to {filename}: {e}") from e

    def get_document(self, doc_id: str) -> RawDocument | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_document(row)

    def get_all_documents(self) -> Iterator[RawDocument]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY retrieved_at DESC")
        for row in cursor:
            yield self._row_to_document(row)

    def get_document_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM documents")
        return cursor.fetchone()[0]

    def get_snippet_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM snippets")
        return cursor.fetchone()[0]

    def get_snippets_for_document(self, doc_id: str) -> list[PainSnippet]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM snippets WHERE doc_id = ?", (doc_id,))
        return [self._row_to_snippet(row) for row in cursor]

    def get_all_snippets(self) -> Iterator[PainSnippet]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM snippets ORDER BY extracted_at DESC")
        for row in cursor:
            yield self._row_to_snippet(row)

    def get_all_entities(self) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT entities FROM snippets")
        all_entities: set[str] = set()
        for row in cursor:
            entities = json.loads(row[0])
            all_entities.update(entities)
        return sorted(all_entities)

    def document_exists(self, doc_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE doc_id = ? LIMIT 1", (doc_id,))
        return cursor.fetchone() is not None

    def _row_to_document(self, row: sqlite3.Row) -> RawDocument:
        return RawDocument(
            doc_id=row["doc_id"],
            source=row["source"],
            source_entity=row["source_entity"],
            url=row["url"],
            permalink=row["permalink"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            title=row["title"],
            raw_text=row["raw_text"],
            author=row["author"],
            score=row["score"],
            num_comments=row["num_comments"],
            metadata=json.loads(row["metadata"]),
        )

    def _row_to_snippet(self, row: sqlite3.Row) -> PainSnippet:
        return PainSnippet(
            snippet_id=row["snippet_id"],
            doc_id=row["doc_id"],
            excerpt=row["excerpt"],
            pain_statement=row["pain_statement"],
            signal_type=row["signal_type"],
            intensity=row["intensity"],
            confidence=row["confidence"],
            entities=json.loads(row["entities"]),
            extractor_model=row["extractor_model"],
            extractor_prompt_version=row["extractor_prompt_version"],
            extracted_at=datetime.fromisoformat(row["extracted_at"]),
            metadata=json.loads(row["metadata"]),
        )

    def export_jsonl(self, output_dir: Path | None = None) -> dict[str, Path]:
        target_dir = output_dir or self.session_dir
        return {
            "documents": target_dir / "raw.jsonl",
            "snippets": target_dir / "snippets.jsonl",
            "events": target_dir / "events.jsonl",
        }


def atomic_write_json(filepath: Path, data: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent, 
        prefix=f".{filepath.name}.", 
        suffix=".tmp"
    )
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        shutil.move(temp_path, filepath)
        logger.debug(f"Atomically wrote {filepath}")
    except Exception:
        if Path(temp_path).exists():
            Path(temp_path).unlink()
        raise


def load_json(filepath: Path) -> dict | None:
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load {filepath}: {e}")
        return None
