# Changelog

All notable changes to **copom-vector-pipeline** will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

## [0.1.0] — 2026-03-25

### Added
- Initial project structure with full package scaffolding.
- `BcbDownloader`: HTTP client for BCB public API (atas and comunicados).
- `PdfParser`: PDF text extraction using pdfplumber.
- `TextChunker`: Recursive character text splitting with tiktoken (500 tokens / 20 overlap).
- `clean_text()`: Regex-based cleaning for COPOM PDF artifacts.
- `EmbeddingProvider` ABC with `embed_text`, `embed_batch`, and `dimensions` interface.
- `GeminiEmbeddingProvider`: Google Gemini `text-embedding-004` (768 dims).
- Registry-decorator factory (`get_embedding_provider`) for zero-code provider switching.
- `PostgresHandler`: psycopg2 wrapper with idempotent upsert and bulk chunk insertion.
- `CopomPipeline`: Dependency-injected orchestrator with checkpoint/resume support.
- `copom-pipeline` CLI with `--doc-type`, `--from-date`, `--to-date`, `--resume`, `--dry-run`.
- `scripts/create_schema.sql`: PostgreSQL schema with `documents` + `chunks` tables and HNSW index.
- Docker Compose setup with `pgvector/pgvector:pg16`.
