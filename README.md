# copom-vector-pipeline

Pipeline de ingestão de dados para documentos do COPOM (Comitê de Política Monetária do Banco Central do Brasil).

Baixa automaticamente Atas e Comunicados do BCB, extrai texto dos PDFs, chunka, gera embeddings e armazena tudo em PostgreSQL + pgvector. É a base do ecossistema [COPOM RAG](#ecossistema).

---

## Ecossistema

Este projeto é um dos três componentes do sistema COPOM RAG:

```
Banco Central (PDFs)
        │
        ▼
copom-vector-pipeline   ← você está aqui (ingestão, chunking, embeddings)
        │
        ▼
PostgreSQL + pgvector   ← banco compartilhado (Neon)
        │
        ▼
copom-rag-api           ← busca semântica + geração via Gemini
        │
        ▼
copom-streamlit         ← interface web para o usuário final
```

---

## Arquitetura

```
BCB API ──► BcbDownloader ──► PdfParser ──► TextCleaner ──► TextChunker
                                                                  │
                                                         EmbeddingProvider
                                                         (Gemini / pluggável)
                                                                  │
                                                         PostgresHandler ──► PostgreSQL + pgvector
```

Todos os colaboradores são injetados em `CopomPipeline` via dependency injection. Trocar qualquer componente (provider de embedding, estratégia de chunking, fonte de documentos) não requer alterações na lógica do pipeline.

---

## Requisitos

- Python 3.11+
- Docker (para PostgreSQL + pgvector local)
- Google Gemini API key

---

## Quick Start

```bash
# 1. Clone e entre no diretório
git clone https://github.com/<org>/copom-vector-pipeline.git
cd copom-vector-pipeline

# 2. Inicie o PostgreSQL + pgvector
docker compose up -d

# 3. Instale o pacote
pip install -e .

# 4. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env e preencha GEMINI_API_KEY e DATABASE_URL

# 5. Aplique o schema (primeira vez)
docker exec -i copom_pgvector psql -U copom -d copom_rag < scripts/create_schema.sql

# 6. Execute o pipeline
copom-pipeline --doc-type all
```

---

## CLI Reference

```
copom-pipeline [OPTIONS]

Options:
  --doc-type {ata,comunicado,all}        Tipos de documento a ingerir (padrão: all)
  --from-date YYYY-MM-DD                 Processar documentos a partir desta data
  --to-date   YYYY-MM-DD                 Processar documentos até esta data
  --resume                               Retomar a partir do último checkpoint
  --dry-run                              Baixa metadados apenas — sem escrita no BD
  --chunk-size INT                       Tamanho dos chunks em tokens (padrão: 500)
  --chunk-overlap INT                    Sobreposição entre chunks em tokens (padrão: 20)
  --batch-size INT                       Batch size para embedding (padrão: 50)
  --checkpoint-interval INT              Salvar checkpoint a cada N documentos (padrão: 20)
  --checkpoint-dir PATH                  Diretório para checkpoints (padrão: ./checkpoints)
  --log-dir PATH                         Diretório para logs (padrão: ./logs)
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

**Exemplos:**

```bash
# Ingerir todos os documentos
copom-pipeline --doc-type all

# Apenas atas de 2024
copom-pipeline --doc-type ata --from-date 2024-01-01 --to-date 2024-12-31

# Retomar ingestão interrompida
copom-pipeline --doc-type all --resume

# Dry-run (sem escrita no banco)
copom-pipeline --doc-type all --dry-run
```

---

## Variáveis de Ambiente

| Variável | Obrigatória | Padrão | Descrição |
|----------|:-----------:|--------|-----------|
| `GEMINI_API_KEY` | **Sim** | — | Google AI API key |
| `DATABASE_URL` | **Sim** | — | PostgreSQL DSN (`postgresql://user:pass@host/db`) |
| `EMBEDDING_PROVIDER` | Não | `gemini` | Provider de embedding |
| `GEMINI_EMBEDDING_MODEL` | Não | `models/gemini-embedding-001` | Modelo de embedding |
| `EMBEDDING_DIMENSIONS` | Não | `1536` | Dimensões do vetor de saída |
| `CHUNK_SIZE` | Não | `500` | Tamanho dos chunks em tokens |
| `CHUNK_OVERLAP` | Não | `20` | Sobreposição entre chunks em tokens |
| `BATCH_SIZE` | Não | `50` | Batch size para embedding |
| `BCB_REQUEST_DELAY_SECONDS` | Não | `1.0` | Delay entre requisições ao BCB |
| `BCB_MAX_RETRIES` | Não | `3` | Tentativas máximas por requisição |

> **Importante:** `GEMINI_EMBEDDING_MODEL` e `EMBEDDING_DIMENSIONS` devem ser idênticos aos configurados na `copom-rag-api`. Se mudar o modelo de embedding, é necessário re-ingerir todos os documentos.

---

## Schema do Banco de Dados

Veja [`scripts/create_schema.sql`](scripts/create_schema.sql).

Duas tabelas:
- **`documents`** — um registro por documento (url, title, doc_type, meeting_date, source_hash)
- **`chunks`** — um registro por chunk de texto, com `embedding vector(1536)` e índice HNSW

A deduplicação é automática via `source_hash` (SHA-256 do conteúdo): re-executar o pipeline não duplica documentos já ingeridos.

---

## Utilitários de Banco

```bash
# Estatísticas gerais
python scripts/db_crud.py stats

# Listar documentos ingeridos
python scripts/db_crud.py list

# Detalhes de um documento
python scripts/db_crud.py show 1

# Busca semântica manual
python scripts/db_crud.py search "taxa Selic 2026"
python scripts/db_crud.py search "inflação" --top-k 10 --doc-type ata

# Deletar um documento
python scripts/db_crud.py delete 3
```

---

## Adicionar um Novo Provider de Embedding

1. Crie `src/copom_pipeline/providers/meu_provider.py`
2. Herde de `EmbeddingProvider` e implemente `embed_text`, `embed_batch` e `dimensions`
3. Decore com `@register_embedding_provider("meu-provider")`
4. Adicione um import em `providers/factory.py` dentro de `_load_providers()`
5. Defina `EMBEDDING_PROVIDER=meu-provider` no `.env`

Nenhum outro arquivo precisa ser alterado.

---

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest tests/
```

---

## Projetos relacionados

- [copom-rag-api](https://github.com/mateusfg7/copom-rag-api) — API RAG que consome o banco vetorial
- [copom-streamlit](https://github.com/mateusfg7/copom-streamlit) — interface web para consultas em linguagem natural
