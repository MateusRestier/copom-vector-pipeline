-- COPOM RAG — PostgreSQL + pgvector schema
-- Applied automatically when the Docker container starts for the first time.

CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────
--  Source documents (one row per PDF file)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id           SERIAL PRIMARY KEY,
    url          TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    -- 'ata'        → meeting minutes (Ata do Copom)
    -- 'comunicado' → policy communication (Comunicado do Copom)
    doc_type     TEXT        NOT NULL CHECK (doc_type IN ('ata', 'comunicado')),
    meeting_date DATE,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- SHA-256 of the raw PDF bytes — used for idempotent re-runs.
    -- The pipeline skips a document whose source_hash already exists.
    source_hash  TEXT        NOT NULL UNIQUE,
    page_count   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_documents_doc_type     ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_meeting_date ON documents (meeting_date);

-- ─────────────────────────────────────────────
--  Text chunks (one row per chunk per document)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id             SERIAL  PRIMARY KEY,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,          -- 0-based position within the document
    -- chunk_text    : original (pre-cleaning) text returned to API consumers
    -- cleaned_text  : cleaned text that was actually fed to the embedding model
    chunk_text     TEXT    NOT NULL,
    cleaned_text   TEXT    NOT NULL,
    -- Dimensionality must match EMBEDDING_DIMENSIONS env var (default 768 for Gemini text-embedding-004).
    embedding      vector(768),
    chunk_strategy TEXT    NOT NULL DEFAULT 'recursive',
    chunk_size     INTEGER NOT NULL,
    chunk_overlap  INTEGER NOT NULL,
    -- SHA-256(chunk_text + strategy + chunk_size + chunk_overlap) — dedup key
    content_hash   TEXT    NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);

-- HNSW index for approximate nearest-neighbour search (cosine distance).
-- m=16 and ef_construction=64 are appropriate for corpora up to ~100k chunks.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
