"""COPOM Vector DB - CRUD helper script.

Uso rápido (rode direto do terminal):
--------------------------------------

    # No diretório copom-vector-pipeline, com o .env configurado:
    python scripts/db_crud.py <comando> [argumentos]

Comandos disponíveis:
---------------------

    stats
        Mostra contagem de documentos e chunks no banco.

        Exemplo:
            python scripts/db_crud.py stats

    list
        Lista todos os documentos ingeridos (id, tipo, data, título).

        Exemplo:
            python scripts/db_crud.py list

    show <id>
        Mostra detalhes de um documento e seus chunks (texto, sem embedding).

        Exemplo:
            python scripts/db_crud.py show 1

    search <query>
        Busca semântica: encontra os chunks mais similares à query usando
        o embedding gerado em tempo real pelo Gemini.

        Opções:
            --top-k N     Número de resultados (padrão: 5)
            --doc-type    Filtra por 'ata' ou 'comunicado'

        Exemplos:
            python scripts/db_crud.py search "decisão sobre taxa Selic"
            python scripts/db_crud.py search "inflação de serviços" --top-k 10
            python scripts/db_crud.py search "cenário externo" --doc-type ata

    delete <id>
        Remove um documento e todos os seus chunks (CASCADE).
        Pede confirmação antes de deletar.

        Exemplo:
            python scripts/db_crud.py delete 3

    delete-all
        Remove TODOS os documentos e chunks do banco.
        Pede confirmação dupla antes de executar.

        Exemplo:
            python scripts/db_crud.py delete-all

Configuração:
-------------
    O script lê DATABASE_URL e GEMINI_API_KEY do arquivo .env na raiz do projeto
    (ou das variáveis de ambiente do sistema).

    DATABASE_URL=postgresql://copom:copom@localhost:5432/copom_rag
    GEMINI_API_KEY=sua-chave-aqui
    GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
    EMBEDDING_DIMENSIONS=1536
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
#  DB connection
# ------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Erro: DATABASE_URL não definida no .env")
    try:
        return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.OperationalError as exc:
        sys.exit(f"Erro ao conectar ao banco: {exc}")


# ------------------------------------------------------------------
#  Commands
# ------------------------------------------------------------------

def cmd_stats(_args) -> None:
    """Exibe estatísticas gerais do banco."""
    conn = _connect()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS total FROM documents")
        total_docs = cur.fetchone()["total"]

        cur.execute("SELECT doc_type, count(*) AS n FROM documents GROUP BY doc_type ORDER BY doc_type")
        by_type = cur.fetchall()

        cur.execute("SELECT count(*) AS total FROM chunks")
        total_chunks = cur.fetchone()["total"]

        cur.execute("SELECT min(meeting_date), max(meeting_date) FROM documents")
        dates = cur.fetchone()

    print(f"\n{'-'*40}")
    print(f"  Documentos : {total_docs}")
    for row in by_type:
        print(f"    {row['doc_type']:12s}: {row['n']}")
    print(f"  Chunks     : {total_chunks}")
    print(f"  Período    : {dates['min']} -> {dates['max']}")
    print(f"{'-'*40}\n")


def cmd_list(_args) -> None:
    """Lista todos os documentos ingeridos."""
    conn = _connect()
    with conn, conn.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.doc_type, d.meeting_date, d.title,
                   count(c.id) AS chunks
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.meeting_date DESC NULLS LAST
        """)
        rows = cur.fetchall()

    if not rows:
        print("Nenhum documento no banco.")
        return

    print(f"\n{'ID':>4}  {'Tipo':12}  {'Data':10}  {'Chunks':>6}  Título")
    print("-" * 80)
    for r in rows:
        date_str = str(r["meeting_date"]) if r["meeting_date"] else "-"
        title = r["title"][:50] + "..." if len(r["title"]) > 51 else r["title"]
        print(f"{r['id']:>4}  {r['doc_type']:12}  {date_str:10}  {r['chunks']:>6}  {title}")
    print()


def cmd_show(args) -> None:
    """Mostra detalhes de um documento e seus chunks."""
    doc_id = args.id
    conn = _connect()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
        doc = cur.fetchone()
        if not doc:
            sys.exit(f"Documento id={doc_id} não encontrado.")

        cur.execute("""
            SELECT chunk_index, chunk_size, chunk_strategy,
                   left(chunk_text, 200) AS preview
            FROM chunks
            WHERE document_id = %s
            ORDER BY chunk_index
        """, (doc_id,))
        chunks = cur.fetchall()

    print(f"\n{'-'*60}")
    print(f"  ID          : {doc['id']}")
    print(f"  Tipo        : {doc['doc_type']}")
    print(f"  Data        : {doc['meeting_date']}")
    print(f"  Título      : {doc['title']}")
    print(f"  URL         : {doc['url']}")
    print(f"  Páginas     : {doc['page_count'] or '-'}")
    print(f"  Ingerido em : {doc['ingested_at']}")
    print(f"  Chunks      : {len(chunks)}")
    print(f"{'-'*60}")

    for c in chunks:
        preview = textwrap.fill(c["preview"], width=70, initial_indent="    ", subsequent_indent="    ")
        print(f"\n  [chunk {c['chunk_index']}]")
        print(preview)
        if len(c["preview"]) == 200:
            print("    ...")
    print()


def cmd_search(args) -> None:
    """Busca semântica: encontra chunks similares à query."""
    query = args.query
    top_k = args.top_k
    doc_type_filter = args.doc_type

    # Generate embedding for the query
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Erro: GEMINI_API_KEY não definida no .env")

    print(f"Gerando embedding para: \"{query}\"...")
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore

        model = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
        dims = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
        client = genai.Client(api_key=api_key)
        result = client.models.embed_content(
            model=model,
            contents=query,
            config=genai_types.EmbedContentConfig(output_dimensionality=dims),
        )
        embedding = list(result.embeddings[0].values)
    except Exception as exc:
        sys.exit(f"Erro ao gerar embedding: {exc}")

    # Vector search
    conn = _connect()
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    where_clause = "WHERE d.doc_type = %(doc_type)s" if doc_type_filter else ""
    sql = f"""
        SELECT
            d.id            AS doc_id,
            d.title,
            d.doc_type,
            d.meeting_date,
            d.url,
            c.chunk_index,
            c.chunk_text,
            1 - (c.embedding <=> %(emb)s::vector) AS similarity
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        {where_clause}
        ORDER BY c.embedding <=> %(emb)s::vector
        LIMIT %(top_k)s
    """
    params = {"emb": embedding_str, "top_k": top_k, "doc_type": doc_type_filter}

    with conn, conn.cursor() as cur:
        cur.execute(sql, params)
        results = cur.fetchall()

    if not results:
        print("Nenhum resultado encontrado.")
        return

    print(f"\n{'-'*60}")
    print(f"  Top {top_k} resultados para: \"{query}\"")
    if doc_type_filter:
        print(f"  Filtro: doc_type = {doc_type_filter}")
    print(f"{'-'*60}")

    for i, r in enumerate(results, 1):
        preview = textwrap.fill(r["chunk_text"][:300], width=68,
                                initial_indent="    ", subsequent_indent="    ")
        print(f"\n  [{i}] similaridade={r['similarity']:.4f}")
        print(f"      {r['title']} | {r['meeting_date']} | chunk {r['chunk_index']}")
        print(f"      {r['url']}")
        print(preview)
        if len(r["chunk_text"]) > 300:
            print("    ...")
    print()


def cmd_delete(args) -> None:
    """Remove um documento e seus chunks do banco."""
    doc_id = args.id
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT title, doc_type, meeting_date FROM documents WHERE id = %s", (doc_id,))
        doc = cur.fetchone()
        if not doc:
            sys.exit(f"Documento id={doc_id} não encontrado.")

        cur.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s", (doc_id,))
        chunk_count = cur.fetchone()["n"]

    print(f"\n  Documento : {doc['title']}")
    print(f"  Tipo      : {doc['doc_type']}")
    print(f"  Data      : {doc['meeting_date']}")
    print(f"  Chunks    : {chunk_count}")
    confirm = input("\nConfirma exclusão? (s/N) ").strip().lower()
    if confirm != "s":
        print("Cancelado.")
        return

    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    print(f"Documento id={doc_id} e seus {chunk_count} chunks foram removidos.\n")


def cmd_delete_all(_args) -> None:
    """Remove TODOS os documentos e chunks do banco."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS docs FROM documents")
        n_docs = cur.fetchone()["docs"]
        cur.execute("SELECT count(*) AS chunks FROM chunks")
        n_chunks = cur.fetchone()["chunks"]

    print(f"\n  ATENÇÃO: isso apagará {n_docs} documentos e {n_chunks} chunks.")
    confirm1 = input("  Tem certeza? (s/N) ").strip().lower()
    if confirm1 != "s":
        print("Cancelado.")
        return
    confirm2 = input("  Confirme digitando 'APAGAR TUDO': ").strip()
    if confirm2 != "APAGAR TUDO":
        print("Cancelado.")
        return

    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM documents")
    print(f"Banco limpo: {n_docs} documentos e {n_chunks} chunks removidos.\n")


# ------------------------------------------------------------------
#  CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="db_crud.py",
        description="CRUD helper para o banco vetorial do COPOM RAG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="<comando>")

    sub.add_parser("stats", help="Estatísticas gerais do banco")
    sub.add_parser("list", help="Lista todos os documentos")

    p_show = sub.add_parser("show", help="Detalhes de um documento e seus chunks")
    p_show.add_argument("id", type=int, metavar="<id>")

    p_search = sub.add_parser("search", help="Busca semântica por similaridade vetorial")
    p_search.add_argument("query", metavar="<query>")
    p_search.add_argument("--top-k", type=int, default=5, metavar="N")
    p_search.add_argument("--doc-type", choices=["ata", "comunicado"], default=None)

    p_delete = sub.add_parser("delete", help="Remove um documento (e seus chunks)")
    p_delete.add_argument("id", type=int, metavar="<id>")

    sub.add_parser("delete-all", help="Remove TODOS os documentos e chunks")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "stats":      cmd_stats,
        "list":       cmd_list,
        "show":       cmd_show,
        "search":     cmd_search,
        "delete":     cmd_delete,
        "delete-all": cmd_delete_all,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
