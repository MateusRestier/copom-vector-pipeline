# copom-vector-pipeline

Data ingestion pipeline for COPOM (Comitê de Política Monetária do Banco Central do Brasil) documents.

Automatically downloads Minutes and Communications from the BCB, extracts text from PDFs, chunks the content, generates embeddings, and stores everything in PostgreSQL + pgvector. It is the data foundation of the [COPOM RAG](#ecosystem) ecosystem.

---

## Ecosystem

This project is one of three components of the COPOM RAG system:

```
Banco Central (PDFs)
        │
        ▼
copom-vector-pipeline   ← you are here (ingestion, chunking, embeddings)
        │
        ▼
PostgreSQL + pgvector   ← shared vector database (Neon)
        │
        ▼
copom-rag-api           ← semantic search + generation via Gemini
        │
        ▼
copom-streamlit         ← web interface for end users
```

---

## Architecture

```
BCB API ──► BcbDownloader ──► PdfParser ──► TextCleaner ──► TextChunker
                                                                  │
                                                         EmbeddingProvider
                                                         (Gemini / pluggable)
                                                                  │
                                                         PostgresHandler ──► PostgreSQL + pgvector
```

All collaborators are wired together by `CopomPipeline` using dependency injection. Swapping any component (embedding provider, chunking strategy, document source) does not require touching the pipeline logic.

---

## Requirements

- Python 3.11+
- Docker (for local PostgreSQL + pgvector)
- Google Gemini API key

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/<org>/copom-vector-pipeline.git
cd copom-vector-pipeline

# 2. Start PostgreSQL + pgvector
docker compose up -d

# 3. Install the package
pip install -e .

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in GEMINI_API_KEY and DATABASE_URL

# 5. Apply the database schema (first time only)
docker exec -i copom_pgvector psql -U copom -d copom_rag < scripts/create_schema.sql

# 6. Run the pipeline
copom-pipeline --doc-type all
```

---

## CLI Reference

```
copom-pipeline [OPTIONS]

Options:
  --doc-type {ata,comunicado,all}        Document types to ingest (default: all)
  --from-date YYYY-MM-DD                 Only process documents from this date
  --to-date   YYYY-MM-DD                 Only process documents up to this date
  --resume                               Resume from the last saved checkpoint
  --dry-run                              Fetch metadata only — no DB writes
  --chunk-size INT                       Token chunk size (default: 500)
  --chunk-overlap INT                    Token overlap between chunks (default: 20)
  --batch-size INT                       Embedding batch size (default: 50)
  --checkpoint-interval INT              Save checkpoint every N documents (default: 20)
  --checkpoint-dir PATH                  Directory for checkpoint files (default: ./checkpoints)
  --log-dir PATH                         Directory for log files (default: ./logs)
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

**Examples:**

```bash
# Ingest all document types
copom-pipeline --doc-type all

# Only minutes from 2024
copom-pipeline --doc-type ata --from-date 2024-01-01 --to-date 2024-12-31

# Resume an interrupted run
copom-pipeline --doc-type all --resume

# Dry-run (no database writes)
copom-pipeline --doc-type all --dry-run
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `GEMINI_API_KEY` | **Yes** | — | Google AI API key |
| `DATABASE_URL` | **Yes** | — | PostgreSQL DSN (`postgresql://user:pass@host/db`) |
| `EMBEDDING_PROVIDER` | No | `gemini` | Embedding provider name |
| `GEMINI_EMBEDDING_MODEL` | No | `models/gemini-embedding-001` | Gemini embedding model |
| `EMBEDDING_DIMENSIONS` | No | `1536` | Output vector dimensions |
| `CHUNK_SIZE` | No | `500` | Chunk size in tokens |
| `CHUNK_OVERLAP` | No | `20` | Overlap between chunks in tokens |
| `BATCH_SIZE` | No | `50` | Embedding batch size |
| `BCB_REQUEST_DELAY_SECONDS` | No | `1.0` | Delay between HTTP requests to BCB |
| `BCB_MAX_RETRIES` | No | `3` | Max retries per HTTP request |

> **Important:** `GEMINI_EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` must be identical to those configured in `copom-rag-api`. Changing the embedding model requires re-ingesting all documents.

---

## Database Schema

See [`scripts/create_schema.sql`](scripts/create_schema.sql).

Two tables:
- **`documents`** — one row per document (url, title, doc_type, meeting_date, source_hash)
- **`chunks`** — one row per text chunk, with `embedding vector(1536)` and an HNSW index

Deduplication is automatic via `source_hash` (SHA-256 of the content): re-running the pipeline will not duplicate already-ingested documents.

---

## Database Utilities

```bash
# General stats
python scripts/db_crud.py stats

# List ingested documents
python scripts/db_crud.py list

# Show details of a document
python scripts/db_crud.py show 1

# Manual semantic search
python scripts/db_crud.py search "taxa Selic 2026"
python scripts/db_crud.py search "inflação" --top-k 10 --doc-type ata

# Delete a document
python scripts/db_crud.py delete 3
```

---

## Adding a New Embedding Provider

1. Create `src/copom_pipeline/providers/my_provider.py`
2. Subclass `EmbeddingProvider` and implement `embed_text`, `embed_batch`, and `dimensions`
3. Decorate the class with `@register_embedding_provider("my-provider")`
4. Add an import in `providers/factory.py` inside `_load_providers()`
5. Set `EMBEDDING_PROVIDER=my-provider` in `.env`

No other files need to change.

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

---

## Related projects

- [copom-rag-api](https://github.com/mateusfg7/copom-rag-api) — RAG API that consumes the vector database
- [copom-streamlit](https://github.com/mateusfg7/copom-streamlit) — web interface for natural language queries
