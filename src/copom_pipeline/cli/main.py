"""CLI entry point for the COPOM vector pipeline.

Usage:
    copom-pipeline --doc-type ata --from-date 2024-01-01
    copom-pipeline --doc-type all --dry-run
    copom-pipeline --doc-type comunicado --resume

Installed as: copom-pipeline (see pyproject.toml [project.scripts])
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from dotenv import load_dotenv


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="copom-pipeline",
        description="Ingest COPOM documents (atas and comunicados) into PostgreSQL+pgvector.",
    )
    p.add_argument(
        "--doc-type",
        choices=["ata", "comunicado", "all"],
        default="all",
        help="Document type to ingest (default: all).",
    )
    p.add_argument("--from-date", metavar="YYYY-MM-DD", help="Only process documents from this date.")
    p.add_argument("--to-date", metavar="YYYY-MM-DD", help="Only process documents up to this date.")
    p.add_argument("--resume", action="store_true", help="Resume from the last checkpoint.")
    p.add_argument("--dry-run", action="store_true", help="Fetch metadata only — no DB writes.")
    p.add_argument("--chunk-size", type=int, default=None, help="Chunk size in tokens (default from env or 500).")
    p.add_argument("--chunk-overlap", type=int, default=None, help="Chunk overlap in tokens (default from env or 20).")
    p.add_argument("--batch-size", type=int, default=None, help="Embedding batch size (default from env or 50).")
    p.add_argument("--checkpoint-interval", type=int, default=None, help="Save checkpoint every N documents.")
    p.add_argument("--checkpoint-dir", default="./checkpoints", help="Directory for checkpoint files.")
    p.add_argument("--log-dir", default="./logs", help="Directory for log files.")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main() -> None:
    load_dotenv()

    args = _build_parser().parse_args()

    from copom_pipeline.utils.logging_config import setup_logging
    setup_logging(log_dir=args.log_dir, level=args.log_level)

    import logging
    logger = logging.getLogger(__name__)

    # ── Resolve parameters ─────────────────────────────────────────
    doc_types = ["ata", "comunicado"] if args.doc_type == "all" else [args.doc_type]
    date_from = _parse_date(args.from_date)
    date_to = _parse_date(args.to_date)

    chunk_size = args.chunk_size or int(os.environ.get("CHUNK_SIZE", "500"))
    chunk_overlap = args.chunk_overlap or int(os.environ.get("CHUNK_OVERLAP", "20"))
    batch_size = args.batch_size or int(os.environ.get("BATCH_SIZE", "50"))
    checkpoint_interval = args.checkpoint_interval or int(os.environ.get("CHECKPOINT_INTERVAL", "20"))

    logger.info(
        "Starting copom-pipeline | doc_types=%s | from=%s | to=%s | dry_run=%s",
        doc_types, date_from, date_to, args.dry_run,
    )

    # ── Build collaborators ────────────────────────────────────────
    from copom_pipeline.database.postgres_handler import PostgresHandler
    from copom_pipeline.ingestion.bcb_downloader import BcbDownloader
    from copom_pipeline.ingestion.pdf_parser import PdfParser
    from copom_pipeline.providers.factory import get_embedding_provider
    from copom_pipeline.text_processing.chunker import TextChunker
    from copom_pipeline.utils.checkpoint_manager import CheckpointManager
    from copom_pipeline.core.pipeline import CopomPipeline

    embedding_provider = get_embedding_provider()
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    checkpoint_mgr = CheckpointManager(checkpoint_dir=args.checkpoint_dir)

    if args.resume:
        state = checkpoint_mgr.load()
        if state is None:
            logger.warning("--resume requested but no checkpoint found. Starting fresh.")
        else:
            logger.info("Resuming from checkpoint (processed=%d).", state.get("processed_count", 0))
            try:
                checkpoint_mgr.validate(
                    embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004"),
                    embedding_dimensions=embedding_provider.dimensions,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            except ValueError as exc:
                logger.error("Checkpoint validation failed:\n%s", exc)
                sys.exit(1)

    db = PostgresHandler()
    try:
        if not args.dry_run:
            db.connect()

        pipeline = CopomPipeline(
            downloader=BcbDownloader(),
            parser=PdfParser(),
            chunker=chunker,
            embedding_provider=embedding_provider,
            db_handler=db,
            checkpoint_manager=checkpoint_mgr,
            batch_size=batch_size,
            checkpoint_interval=checkpoint_interval,
            skip_errors=True,
            dry_run=args.dry_run,
        )

        summary = pipeline.run(doc_types=doc_types, date_from=date_from, date_to=date_to)
        logger.info("Done. Summary: %s", summary)

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)
    finally:
        db.close()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        print(f"Invalid date format: '{value}'. Expected YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
