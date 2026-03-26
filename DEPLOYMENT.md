# Deployment Guide — copom-vector-pipeline

This pipeline runs **locally** and writes embeddings directly to the production database (Neon).
There is no hosted service for the pipeline itself.

---

## Production Stack

| Component | Service | Notes |
|-----------|---------|-------|
| Vector database | [Neon](https://neon.tech) (free tier) | PostgreSQL 17 + pgvector, project `copom-rag` |
| Embedding model | Google Gemini (`gemini-embedding-001`) | 1536-dim output, free tier: 100 req/min |

---

## Initial Setup (already done)

The following steps were completed during the first deploy and do not need to be repeated
unless you are setting up a brand-new environment.

### 1. Create the Neon project

1. Go to [neon.tech](https://neon.tech) and create a project named `copom-rag`
2. Region: AWS South America (São Paulo) if available, otherwise US East
3. Postgres version: 17

### 2. Apply the database schema

Open the **SQL Editor** in the Neon dashboard (left sidebar) and run the contents of
`scripts/create_schema.sql`. This creates the `documents` and `chunks` tables and the
HNSW index for vector search.

### 3. Configure the local environment

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Set `DATABASE_URL` to the Neon connection string (see [Getting the Neon connection string](#getting-the-neon-connection-string) below).

---

## Running an Ingestion

Use the `copom-pipeline` CLI to ingest documents into the production database.
The pipeline is idempotent — documents already in the database (matched by SHA-256 hash)
are skipped automatically.

### Ingest recent documents (recommended for routine updates)

```bash
# Ingest all atas and comunicados from the current year
copom-pipeline --doc-type all --from-date 2026-01-01

# Ingest only atas from a specific period
copom-pipeline --doc-type ata --from-date 2025-01-01 --to-date 2025-12-31

# Ingest only comunicados
copom-pipeline --doc-type comunicado --from-date 2026-01-01
```

### Ingest the full historical archive

```bash
copom-pipeline --doc-type all --from-date 2015-01-01
```

> **Note:** The free tier of the Gemini embedding API allows 100 requests per minute.
> The pipeline automatically detects rate limit errors (HTTP 429) and waits the required
> delay before retrying. A full historical ingestion (~250 atas + ~230 comunicados) takes
> around 30–60 minutes due to these pauses.

### Dry run (no writes to DB)

```bash
copom-pipeline --doc-type all --from-date 2026-01-01 --dry-run
```

---

## Getting the Neon Connection String

You will need this when rotating credentials or setting up a new environment.

1. Go to [neon.tech](https://neon.tech) → project `copom-rag`
2. Click on the **`main`** branch (left sidebar → Branches → main)
3. Go to the **Roles & Databases** tab
4. Click the **⋮** menu next to `neondb_owner` → **Reset password** (or view existing)
5. Copy the connection string from the **Overview** tab or build it manually:

```
postgresql://neondb_owner:<PASSWORD>@ep-bitter-sunset-acbajs1b-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

Replace `<PASSWORD>` with the password obtained in step 4.

---

## Rotating the Database Password

If the Neon password needs to be rotated:

1. In Neon: Branches → main → Roles & Databases → ⋮ next to `neondb_owner` → **Reset password**
2. Copy the new password and build the new connection string (see above)
3. Update `DATABASE_URL` in your local `.env`
4. Update `DATABASE_URL` in the Render environment variables (see [copom-rag-api DEPLOYMENT.md](../copom-rag-api/DEPLOYMENT.md))
5. Update `DATABASE_URL` in any other services that connect to this database

---

## Checking What Is in the Database

Use the CRUD helper script to inspect the database without writing code:

```bash
# Summary: document count, chunk count, date range
python scripts/db_crud.py stats

# List all documents
python scripts/db_crud.py list

# Show details for a specific document (by ID)
python scripts/db_crud.py show 1

# Semantic search (generates a real embedding and queries pgvector)
python scripts/db_crud.py search "taxa Selic 2026"
```

---

## Troubleshooting

### `RESOURCE_EXHAUSTED` / rate limit errors during ingestion

The Gemini free tier allows 100 embedding requests per minute. The pipeline handles this
automatically by sleeping and retrying. If you see these errors, the pipeline is working
correctly — it will resume after the wait period shown in the log.

### `DATABASE_URL` connection refused

Make sure `DATABASE_URL` in `.env` points to the Neon connection string, not `localhost`.
The local Docker Compose database is only used for local development.

### `GEMINI_API_KEY` not set

Set `GEMINI_API_KEY` in `.env` with a valid key from [Google AI Studio](https://aistudio.google.com/apikey).

### Schema already exists error

The schema uses `CREATE TABLE IF NOT EXISTS` — it is safe to run `create_schema.sql`
multiple times. Existing data will not be affected.
