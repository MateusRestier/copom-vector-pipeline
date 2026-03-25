"""Text chunking for embedding preparation.

Uses LangChain's RecursiveCharacterTextSplitter with tiktoken encoding,
ported from document-vector-pipeline with the same parameter names so
CheckpointManager validation logic is compatible.

Default parameters:
    chunk_size    = 500 tokens
    chunk_overlap = 20 tokens
    min_ratio     = 0.5  (chunks smaller than 50% of chunk_size are merged
                          into the previous chunk)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_TEXT_BYTES = 10 * 1024 * 1024  # 10 MB hard limit per document
_MAX_CHUNKS_PER_DOC = 1000


class TextChunker:
    """Splits text into token-sized chunks using recursive character splitting.

    Args:
        chunk_size:    Target chunk size in tokens.
        chunk_overlap: Number of overlapping tokens between consecutive chunks.
        min_ratio:     Chunks smaller than (min_ratio * chunk_size) tokens are
                       merged into the previous chunk to avoid tiny trailing chunks.
        strategy:      Chunking strategy name stored in checkpoint metadata.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 20,
        min_ratio: float = 0.5,
        strategy: str = "recursive",
    ) -> None:
        if strategy != "recursive":
            raise ValueError(f"Unsupported chunking strategy '{strategy}'. Only 'recursive' is available.")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_ratio = min_ratio
        self.strategy = strategy
        self._splitter = None  # lazy init

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def chunk_text(self, text: str) -> list[str]:
        """Split text into chunks. Returns a list of chunk strings.

        Returns an empty list if the text is empty or exceeds the size limit.
        """
        if not text or not text.strip():
            return []

        if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
            logger.warning(
                "Text exceeds 10 MB limit (%d bytes) — skipping.", len(text.encode("utf-8"))
            )
            return []

        splitter = self._get_splitter()
        chunks = splitter.split_text(text)

        if not chunks:
            return []

        # Merge trailing short chunk into its predecessor
        min_tokens = int(self.chunk_size * self.min_ratio)
        if len(chunks) > 1:
            last = chunks[-1]
            last_token_count = self._estimate_tokens(last)
            if last_token_count < min_tokens:
                chunks[-2] = chunks[-2] + " " + last
                chunks = chunks[:-1]

        if len(chunks) > _MAX_CHUNKS_PER_DOC:
            logger.warning(
                "Document produced %d chunks; truncating to %d.",
                len(chunks), _MAX_CHUNKS_PER_DOC,
            )
            chunks = chunks[:_MAX_CHUNKS_PER_DOC]

        return chunks

    def params_dict(self) -> dict:
        """Return a dict of chunking params for checkpoint validation."""
        return {
            "chunk_strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    # ──────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _get_splitter(self):
        if self._splitter is None:
            try:
                from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
            except ImportError:
                raise ImportError(
                    "langchain-text-splitters is required. "
                    "Install it with: pip install langchain-text-splitters"
                )
            self._splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
        return self._splitter

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (4 chars ≈ 1 token) used only for min_ratio check."""
        return max(1, len(text) // 4)
