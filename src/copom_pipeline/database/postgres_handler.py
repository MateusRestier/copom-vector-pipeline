"""PostgreSQL + pgvector handler for the COPOM pipeline.

Responsibilities:
  - Manage a simple connection (not pooled — pipeline is single-process).
  - Provide idempotent upsert for documents (ON CONFLICT on source_hash).
  - Bulk-insert chunks via psycopg2 execute_values for performance.
  - Load the set of already-ingested source_hash values for pre-flight dedup.

Required env var:
    DATABASE_URL — PostgreSQL DSN, e.g.:
        postgresql://copom:copom@localhost:5432/copom_rag
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


@dataclass
class ChunkRow:
    """All fields needed to insert one chunk into the database."""
    document_id: int
    chunk_index: int
    chunk_text: str
    cleaned_text: str
    embedding: list[float]
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    content_hash: str


class PostgresHandler:
    """Thin wrapper around psycopg2 for the COPOM pipeline.

    Args:
        dsn: PostgreSQL connection string.  Defaults to DATABASE_URL env var.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        if not self._dsn:
            raise EnvironmentError(
                "DATABASE_URL environment variable is not set. "
                "Set it in your .env file or pass dsn= explicitly."
            )
        self._conn = None

    # ──────────────────────────────────────────────────────────────────
    #  Connection lifecycle
    # ──────────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the database connection and register the pgvector type."""
        import psycopg2  # type: ignore
        from pgvector.psycopg2 import register_vector  # type: ignore

        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = False
        register_vector(self._conn)
        logger.info("Connected to PostgreSQL.")

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("PostgreSQL connection closed.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, *_):
        if exc_type:
            self._conn.rollback()
        self.close()

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def get_known_hashes(self) -> set[str]:
        """Return the set of source_hash values already in the documents table."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT source_hash FROM documents;")
            return {row[0] for row in cur.fetchall()}

    def upsert_document(
        self,
        url: str,
        title: str,
        doc_type: str,
        meeting_date: date | None,
        source_hash: str,
        page_count: int | None,
    ) -> int:
        """Insert a document row, skipping if source_hash already exists.

        Returns the document id (existing or newly created).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (url, title, doc_type, meeting_date, source_hash, page_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_hash) DO NOTHING
                RETURNING id;
                """,
                (url, title, doc_type, meeting_date, source_hash, page_count),
            )
            row = cur.fetchone()
            if row:
                self._conn.commit()
                return row[0]

            # source_hash already existed — fetch the existing id
            cur.execute("SELECT id FROM documents WHERE source_hash = %s;", (source_hash,))
            existing = cur.fetchone()
            if existing:
                return existing[0]
            raise RuntimeError(f"Unexpected state: no document row for hash {source_hash}")

    def insert_chunks(self, chunks: list[ChunkRow]) -> int:
        """Bulk-insert chunk rows.  Skips rows that violate the UNIQUE constraint.

        Returns the number of rows actually inserted.
        """
        if not chunks:
            return 0

        import numpy as np
        from psycopg2.extras import execute_values  # type: ignore

        rows = [
            (
                c.document_id,
                c.chunk_index,
                c.chunk_text,
                c.cleaned_text,
                np.array(c.embedding, dtype=np.float32),
                c.chunk_strategy,
                c.chunk_size,
                c.chunk_overlap,
                c.content_hash,
            )
            for c in chunks
        ]

        with self._conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO chunks
                    (document_id, chunk_index, chunk_text, cleaned_text, embedding,
                     chunk_strategy, chunk_size, chunk_overlap, content_hash)
                VALUES %s
                ON CONFLICT (document_id, chunk_index, content_hash) DO NOTHING;
                """,
                rows,
            )
            inserted = cur.rowcount
        self._conn.commit()
        return max(inserted, 0)

    def chunk_count(self) -> int:
        """Return the total number of chunk rows (for reporting)."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks;")
            return cur.fetchone()[0]
