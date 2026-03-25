"""SHA-256 hashing utilities for deduplication."""

from __future__ import annotations

import hashlib


def hash_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of raw bytes (used for source_hash)."""
    return hashlib.sha256(data).hexdigest()


def hash_chunk(chunk_text: str, strategy: str, chunk_size: int, chunk_overlap: int) -> str:
    """Return a deterministic hash for a chunk + its chunking parameters.

    This is used as content_hash in the chunks table to ensure that
    re-chunking with different parameters does not collide with existing rows.
    """
    key = f"{chunk_text}\x00{strategy}\x00{chunk_size}\x00{chunk_overlap}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
