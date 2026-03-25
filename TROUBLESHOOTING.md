# Troubleshooting

Common issues and solutions for **copom-vector-pipeline**.

---

## Database connection errors

### `EnvironmentError: DATABASE_URL environment variable is not set`

**Cause**: The `.env` file is missing or `DATABASE_URL` is not defined.

**Fix**:
```bash
cp .env.example .env
# Set DATABASE_URL in .env:
DATABASE_URL=postgresql://copom:copom@localhost:5432/copom_rag
```

---

### `psycopg2.OperationalError: could not connect to server`

**Cause**: PostgreSQL container is not running or is still starting up.

**Fix**:
```bash
docker compose up -d
# Wait for the container to be healthy:
docker compose ps
# Connect to verify:
docker exec -it copom_pgvector psql -U copom -d copom_rag -c "SELECT 1;"
```

---

### `relation "documents" does not exist`

**Cause**: The schema was not applied. This can happen if the container was started before the SQL file was mounted, or if the volume already existed without the schema.

**Fix**:
```bash
# Option 1: Apply the schema manually
docker exec -i copom_pgvector psql -U copom -d copom_rag < scripts/create_schema.sql

# Option 2: Reset the volume and restart (data loss)
docker compose down -v
docker compose up -d
```

---

## Embedding / provider errors

### `EnvironmentError: GEMINI_API_KEY environment variable is not set`

**Fix**: Add `GEMINI_API_KEY=your-key-here` to your `.env` file.

---

### `ValueError: Unknown embedding provider 'openai'`

**Cause**: `EMBEDDING_PROVIDER=openai` is set but no OpenAI provider is registered.

**Fix**: Either set `EMBEDDING_PROVIDER=gemini`, or implement an OpenAI provider following the guide in [README.md](README.md#adding-a-new-embedding-provider).

---

### Dimension mismatch on resume

**Symptom**: `ValueError: Cannot resume: run parameters differ from checkpoint. embedding_dimensions: checkpoint=768, current=1536`

**Cause**: `EMBEDDING_PROVIDER` or `GEMINI_EMBEDDING_MODEL` was changed between runs.

**Fix**: Do not change embedding models mid-run. To switch models on an existing database you must re-ingest all documents.
```bash
# Delete the checkpoint to start fresh with the new model:
rm checkpoints/copom.json
```

---

## Chunking issues

### `ValueError: Unsupported chunking strategy 'sentence'`

**Cause**: Only `'recursive'` is currently supported.

**Fix**: Remove `--chunk-strategy` flag or leave it at the default.

---

### Documents produce 0 chunks

**Cause**: Text was empty after cleaning, or the PDF could not be parsed.

**Fix**: Run with `--log-level DEBUG` to see which document is failing, then inspect the PDF manually.

---

## Checkpoint issues

### `ValueError: Cannot resume: run parameters differ from checkpoint`

**Cause**: CLI parameters (`--chunk-size`, `--chunk-overlap`) differ from the saved checkpoint.

**Fix**: Either use the same parameters as the original run, or delete the checkpoint:
```bash
rm checkpoints/copom.json
```

---

## BCB download issues

### HTTP 403 / 404 on PDF downloads

**Cause**: Some BCB documents may have been moved or removed from the public site.

**Behaviour**: The pipeline logs a warning and skips the document — it does not crash.

---

### `RuntimeError: Failed to fetch JSON after 3 attempts`

**Cause**: Network issue or BCB API is temporarily unavailable.

**Fix**: Check your internet connection, then re-run with `--resume` to retry from the last checkpoint.
```bash
copom-pipeline --doc-type all --resume
```
