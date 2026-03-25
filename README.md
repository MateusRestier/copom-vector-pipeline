# copom-vector-pipeline

Data ingestion pipeline for COPOM (Comitê de Política Monetária) documents.

Downloads meeting minutes (**atas**) and policy communications (**comunicados**) from the Banco Central do Brasil, parses the PDFs, chunks the text, generates embeddings, and stores everything in PostgreSQL + pgvector.

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
- Docker (for PostgreSQL + pgvector)
- A Google Gemini API key (or another configured provider)

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/<org>/copom-vector-pipeline.git
cd copom-vector-pipeline

# 2. Start PostgreSQL + pgvector
docker compose up -d
# The schema is applied automatically on first container start.

# 3. Install the package
pip install -e .

# 4. Configure environment variables
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 5. Run the pipeline
copom-pipeline --doc-type all
```

---

## CLI Reference

```
copom-pipeline [OPTIONS]

Options:
  --doc-type {ata,comunicado,all}   Document types to ingest (default: all)
  --from-date YYYY-MM-DD            Only process documents from this date
  --to-date   YYYY-MM-DD            Only process documents up to this date
  --resume                          Resume from the last saved checkpoint
  --dry-run                         Fetch metadata only — no DB writes
  --chunk-size INT                  Token chunk size (default: 500)
  --chunk-overlap INT               Token overlap between chunks (default: 20)
  --batch-size INT                  Embedding batch size (default: 50)
  --checkpoint-interval INT         Save checkpoint every N documents (default: 20)
  --checkpoint-dir PATH             Directory for checkpoint files (default: ./checkpoints)
  --log-dir PATH                    Directory for log files (default: ./logs)
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | No | `gemini` | Provider name. Change to swap providers. |
| `GEMINI_API_KEY` | Yes | — | Google AI API key. |
| `GEMINI_EMBEDDING_MODEL` | No | `models/text-embedding-004` | Gemini embedding model. |
| `EMBEDDING_DIMENSIONS` | No | `768` | Must match the model's output dimensions. |
| `DATABASE_URL` | Yes | — | PostgreSQL DSN, e.g. `postgresql://user:pass@host/db`. |
| `CHUNK_SIZE` | No | `500` | Default chunk size in tokens. |
| `CHUNK_OVERLAP` | No | `20` | Default chunk overlap in tokens. |
| `BATCH_SIZE` | No | `50` | Default embedding batch size. |
| `BCB_REQUEST_DELAY_SECONDS` | No | `1.0` | Polite delay between HTTP requests. |
| `BCB_MAX_RETRIES` | No | `3` | Max retries per HTTP request. |

---

## Adding a New Embedding Provider

1. Create `src/copom_pipeline/providers/my_provider.py`.
2. Subclass `EmbeddingProvider` and implement `embed_text`, `embed_batch`, and `dimensions`.
3. Decorate the class with `@register_embedding_provider("my-provider")`.
4. Add an import line in `providers/factory.py` inside `_load_providers()`.
5. Set `EMBEDDING_PROVIDER=my-provider` in `.env`.

No other files need to change.

---

## Database Schema

See [`scripts/create_schema.sql`](scripts/create_schema.sql).

Two tables:
- **`documents`** — one row per PDF (url, title, doc_type, meeting_date, source_hash)
- **`chunks`** — one row per text chunk, with `embedding vector(768)` and HNSW index

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```
