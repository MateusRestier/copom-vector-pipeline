"""CopomPipeline — main orchestrator.

Wires together all collaborators via dependency injection and runs the
full ETL loop: download → parse → clean → chunk → embed → store.

All collaborators are injected through the constructor so they can be
swapped in tests or for different configurations without modifying this class.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from tqdm import tqdm  # type: ignore

from copom_pipeline.database.postgres_handler import ChunkRow, PostgresHandler
from copom_pipeline.ingestion.bcb_downloader import BcbDownloader
from copom_pipeline.ingestion.pdf_parser import PdfParser
from copom_pipeline.providers.base import EmbeddingProvider
from copom_pipeline.text_processing.chunker import TextChunker
from copom_pipeline.text_processing.cleaning import clean_text
from copom_pipeline.utils.checkpoint_manager import CheckpointManager
from copom_pipeline.utils.hashing import hash_bytes, hash_chunk

logger = logging.getLogger(__name__)


class CopomPipeline:
    """End-to-end COPOM document ingestion pipeline.

    Args:
        downloader:           BcbDownloader instance.
        parser:               PdfParser instance.
        chunker:              TextChunker instance.
        embedding_provider:   EmbeddingProvider instance.
        db_handler:           PostgresHandler instance (must already be connected).
        checkpoint_manager:   Optional CheckpointManager for resume support.
        batch_size:           Number of chunks to embed+insert per DB transaction.
        checkpoint_interval:  Save a checkpoint every N documents processed.
        skip_errors:          If True, log and continue on per-document errors.
        dry_run:              If True, download metadata only — no DB writes.
    """

    def __init__(
        self,
        downloader: BcbDownloader,
        parser: PdfParser,
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        db_handler: PostgresHandler,
        checkpoint_manager: CheckpointManager | None = None,
        batch_size: int = 50,
        checkpoint_interval: int = 20,
        skip_errors: bool = True,
        dry_run: bool = False,
    ) -> None:
        self._downloader = downloader
        self._parser = parser
        self._chunker = chunker
        self._embedding = embedding_provider
        self._db = db_handler
        self._checkpoint = checkpoint_manager
        self._batch_size = batch_size
        self._checkpoint_interval = checkpoint_interval
        self._skip_errors = skip_errors
        self._dry_run = dry_run

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def run(
        self,
        doc_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Execute the pipeline.

        Args:
            doc_types: Which document types to process. Defaults to both.
            date_from: Only process documents on or after this date.
            date_to:   Only process documents on or before this date.

        Returns:
            A summary dict with counts of documents and chunks processed.
        """
        if doc_types is None:
            doc_types = ["ata", "comunicado"]

        # Pre-flight: validate checkpoint compatibility
        if self._checkpoint:
            self._checkpoint.validate(
                embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004"),
                embedding_dimensions=self._embedding.dimensions,
                chunk_size=self._chunker.chunk_size,
                chunk_overlap=self._chunker.chunk_overlap,
            )

        # Load already-ingested hashes to skip known documents
        known_hashes: set[str] = set()
        if not self._dry_run:
            known_hashes = self._db.get_known_hashes()
            logger.info("Skipping %d already-ingested documents.", len(known_hashes))

        total_docs = 0
        total_chunks = 0
        last_url = ""

        with tqdm(desc="Documents", unit="doc") as pbar:
            for raw_doc in self._downloader.iter_documents(
                doc_types=doc_types,
                date_from=date_from,
                date_to=date_to,
                dry_run=self._dry_run,
            ):
                # Dedup key: hash of PDF bytes for PDF docs, hash of text for HTML docs
                if raw_doc.raw_bytes:
                    src_hash = hash_bytes(raw_doc.raw_bytes)
                elif raw_doc.raw_text:
                    src_hash = hash_bytes(raw_doc.raw_text.encode("utf-8"))
                else:
                    src_hash = ""

                if src_hash and src_hash in known_hashes:
                    logger.debug("Skipping already-ingested: %s", raw_doc.title)
                    pbar.update(1)
                    continue

                if self._dry_run:
                    logger.info("[dry-run] %s — %s", raw_doc.doc_type, raw_doc.title)
                    pbar.update(1)
                    continue

                try:
                    chunks_inserted = self._process_document(raw_doc, src_hash)
                    total_docs += 1
                    total_chunks += chunks_inserted
                    last_url = raw_doc.url
                    known_hashes.add(src_hash)
                    pbar.set_postfix(chunks=total_chunks)
                    pbar.update(1)

                    if self._checkpoint and total_docs % self._checkpoint_interval == 0:
                        self._save_checkpoint(last_url, total_docs, doc_types, date_from, date_to)

                except Exception as exc:
                    if self._skip_errors:
                        logger.error("Error processing '%s': %s — skipping.", raw_doc.title, exc)
                        pbar.update(1)
                    else:
                        raise

        if self._checkpoint and last_url:
            self._save_checkpoint(last_url, total_docs, doc_types, date_from, date_to)

        summary = {"documents_processed": total_docs, "chunks_inserted": total_chunks}
        logger.info("Pipeline complete: %s", summary)
        return summary

    # ──────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _process_document(self, raw_doc, src_hash: str) -> int:
        """Parse, chunk, embed and store a single document. Returns chunk count."""
        # Resolve plain text: PDF docs go through PdfParser, HTML docs are used directly.
        if raw_doc.has_pdf:
            parsed = self._parser.parse(raw_doc.raw_bytes)
            if parsed is None:
                logger.warning("Could not parse PDF: %s", raw_doc.title)
                return 0
            raw_text = parsed.text
            page_count = parsed.page_count
        else:
            raw_text = raw_doc.raw_text
            page_count = None

        if not raw_text or not raw_text.strip():
            logger.warning("Empty text for: %s", raw_doc.title)
            return 0

        # Insert document row and get its id
        doc_id = self._db.upsert_document(
            url=raw_doc.url,
            title=raw_doc.title,
            doc_type=raw_doc.doc_type,
            meeting_date=raw_doc.meeting_date,
            source_hash=src_hash,
            page_count=page_count,
        )

        cleaned = clean_text(raw_text)
        text_chunks = self._chunker.chunk_text(cleaned)

        if not text_chunks:
            logger.warning("No chunks produced for: %s", raw_doc.title)
            return 0

        # Embed in batches
        total_inserted = 0
        for batch_start in range(0, len(text_chunks), self._batch_size):
            batch = text_chunks[batch_start: batch_start + self._batch_size]
            embeddings = self._embedding.embed_batch(batch)

            rows = [
                ChunkRow(
                    document_id=doc_id,
                    chunk_index=batch_start + i,
                    chunk_text=raw_chunk,   # original text before cleaning (we pass cleaned here)
                    cleaned_text=raw_chunk,
                    embedding=embeddings[i],
                    chunk_strategy=self._chunker.strategy,
                    chunk_size=self._chunker.chunk_size,
                    chunk_overlap=self._chunker.chunk_overlap,
                    content_hash=hash_chunk(
                        raw_chunk,
                        self._chunker.strategy,
                        self._chunker.chunk_size,
                        self._chunker.chunk_overlap,
                    ),
                )
                for i, raw_chunk in enumerate(batch)
            ]
            total_inserted += self._db.insert_chunks(rows)

        return total_inserted

    def _save_checkpoint(
        self,
        last_url: str,
        processed_count: int,
        doc_types: list[str],
        date_from: date | None,
        date_to: date | None,
    ) -> None:
        if not self._checkpoint:
            return
        doc_type_str = ",".join(doc_types)
        self._checkpoint.save(
            last_processed_url=last_url,
            processed_count=processed_count,
            doc_type=doc_type_str,
            date_from=date_from,
            date_to=date_to,
            embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004"),
            embedding_dimensions=self._embedding.dimensions,
            chunk_size=self._chunker.chunk_size,
            chunk_overlap=self._chunker.chunk_overlap,
        )
