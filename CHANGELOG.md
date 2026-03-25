# Changelog

All notable changes to **copom-vector-pipeline** will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

## [0.1.0] — 2026-03-25

### Added
- `BcbDownloader`: HTTP client for the BCB Open Data API (`/api/servico/sitebcb/copom/`),
  supporting atas (PDF or HTML fallback for older meetings) and comunicados (HTML only).
- `PdfParser`: PDF text extraction using pdfplumber.
- `TextChunker`: Recursive character text splitting with tiktoken (500 tokens / 20 overlap).
- `clean_text()`: Regex-based cleaning for COPOM PDF artifacts (soft hyphens, ligatures,
  repeated headers/footers, hyphenated line breaks). No spaCy dependency.
- `EmbeddingProvider` ABC with `embed_text`, `embed_batch`, and `dimensions` interface.
- `GeminiEmbeddingProvider`: Google Gemini `gemini-embedding-001` via `google-genai` SDK,
  with `output_dimensionality=1536` (native 3072 dims truncated to fit pgvector HNSW limit).
- Registry-decorator factory (`get_embedding_provider`) for zero-code provider switching
  via `EMBEDDING_PROVIDER` env var.
- `PostgresHandler`: psycopg2 wrapper with idempotent upsert (`ON CONFLICT DO NOTHING`)
  and bulk chunk insertion via `execute_values`.
- `CopomPipeline`: Dependency-injected orchestrator with checkpoint/resume support,
  dry-run mode, per-document error skipping, and dedup via SHA-256 source hash.
- `copom-pipeline` CLI with `--doc-type`, `--from-date`, `--to-date`, `--resume`,
  `--dry-run` flags.
- `scripts/create_schema.sql`: PostgreSQL schema with `documents` + `chunks` tables,
  `vector(1536)` embedding column, and HNSW index (`m=16`, `ef_construction=64`).
- `scripts/db_crud.py`: Interactive CRUD helper with `stats`, `list`, `show`, `search`
  (semantic via Gemini embedding), `delete`, and `delete-all` commands.
- Docker Compose setup with `pgvector/pgvector:pg16`.
- README, CHANGELOG, TROUBLESHOOTING (all in English).
