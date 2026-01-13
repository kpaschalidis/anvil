import json
import os
import sqlite3
import tempfile
import shutil
import logging
import threading
import csv
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
        self._lock = threading.Lock()
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
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            cursor.executescript(SCHEMA)
            cursor.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
            self._conn.commit()
            logger.info(f"Database initialized with schema version {SCHEMA_VERSION}")
        else:
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            if row and row[0] != SCHEMA_VERSION:
                logger.warning(
                    f"Schema version mismatch: expected {SCHEMA_VERSION}, got {row[0]}"
                )

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("Database connection not initialized")
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()

    def save_document(self, doc: RawDocument) -> None:
        try:
            with self._lock:
                cursor = self.conn.cursor()
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
        try:
            with self._lock:
                cursor = self.conn.cursor()
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
        with self._lock:
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
        row = self._fetchone("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        if not row:
            return None
        return self._row_to_document(row)

    def get_all_documents(self) -> Iterator[RawDocument]:
        rows = self._fetchall("SELECT * FROM documents ORDER BY retrieved_at DESC")
        for row in rows:
            yield self._row_to_document(row)

    def get_document_count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) FROM documents")
        return int(row[0] if row else 0)

    def get_snippet_count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) FROM snippets")
        return int(row[0] if row else 0)

    def get_snippets_for_document(self, doc_id: str) -> list[PainSnippet]:
        rows = self._fetchall("SELECT * FROM snippets WHERE doc_id = ?", (doc_id,))
        return [self._row_to_snippet(row) for row in rows]

    def get_all_snippets(self) -> Iterator[PainSnippet]:
        rows = self._fetchall("SELECT * FROM snippets ORDER BY extracted_at DESC")
        for row in rows:
            yield self._row_to_snippet(row)

    def get_all_entities(self) -> list[str]:
        all_entities: set[str] = set()
        rows = self._fetchall("SELECT DISTINCT entities FROM snippets")
        for row in rows:
            entities = json.loads(row[0])
            all_entities.update(entities)
        return sorted(all_entities)

    def document_exists(self, doc_id: str) -> bool:
        return (
            self._fetchone(
                "SELECT 1 FROM documents WHERE doc_id = ? LIMIT 1", (doc_id,)
            )
            is not None
        )

    def _row_to_document(self, row: sqlite3.Row) -> RawDocument:
        return RawDocument(
            doc_id=row["doc_id"],
            source=row["source"],
            source_entity=row["source_entity"],
            url=row["url"],
            permalink=row["permalink"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            published_at=(
                datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None
            ),
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

    def export_csv(self, output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "snippet_id",
                    "doc_id",
                    "pain_statement",
                    "signal_type",
                    "intensity",
                    "confidence",
                    "quality_score",
                    "entities",
                    "excerpt",
                    "extracted_at",
                ]
            )
            for snippet in self.get_all_snippets():
                writer.writerow(
                    [
                        snippet.snippet_id,
                        snippet.doc_id,
                        snippet.pain_statement,
                        snippet.signal_type,
                        snippet.intensity,
                        snippet.confidence,
                        snippet.quality_score,
                        "|".join(snippet.entities),
                        snippet.excerpt,
                        snippet.extracted_at.isoformat(),
                    ]
                )
        return output_file

    def export_markdown_summary(
        self, output_file: Path, *, session: "SessionState"
    ) -> Path:
        from scout.models import SessionState

        if not isinstance(session, SessionState):
            raise TypeError("session must be SessionState")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        entities = self.get_all_entities()
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"## Session\n\n")
            f.write(f"- ID: {session.session_id}\n")
            f.write(f"- Topic: {session.topic}\n")
            f.write(f"- Status: {session.status}\n")
            f.write(f"- Created: {session.created_at}\n")
            f.write(f"- Updated: {session.updated_at}\n\n")

            f.write("## Stats\n\n")
            f.write(f"- Documents: {self.get_document_count()}\n")
            f.write(f"- Snippets: {self.get_snippet_count()}\n")
            f.write(f"- Iterations: {session.stats.iterations}\n")
            f.write(f"- Avg novelty: {session.stats.avg_novelty:.2f}\n")
            if session.stats.total_cost_usd:
                f.write(f"- Cost: ${session.stats.total_cost_usd:.4f}\n")
                f.write(f"- Tokens: {session.stats.total_tokens}\n")
            f.write("\n")

            f.write("## Entities\n\n")
            for e in entities[:100]:
                f.write(f"- {e}\n")
            if len(entities) > 100:
                f.write(f"\n... and {len(entities) - 100} more\n")

        return output_file


def atomic_write_json(filepath: Path, data: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent, prefix=f".{filepath.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
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
