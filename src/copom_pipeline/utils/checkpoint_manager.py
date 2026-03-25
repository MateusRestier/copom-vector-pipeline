"""Checkpoint manager for resumable pipeline runs.

Saves pipeline state to a JSON file after every N documents so that
interrupted runs can resume from where they left off.

Checkpoint file structure:
{
    "last_processed_url": "https://...",
    "processed_count": 42,
    "doc_type": "ata",
    "date_from": "2024-01-01",    // nullable
    "date_to": "2024-12-31",      // nullable
    "embedding_model": "models/text-embedding-004",
    "embedding_dimensions": 768,
    "chunk_size": 500,
    "chunk_overlap": 20,
    "chunk_strategy": "recursive"
}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DIR = "./checkpoints"


class CheckpointManager:
    """Saves and loads pipeline run state from a JSON file.

    Args:
        checkpoint_dir: Directory where checkpoint files are stored.
        run_name:       Unique name for this run (used as filename base).
    """

    def __init__(self, checkpoint_dir: str = _DEFAULT_DIR, run_name: str = "copom") -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{run_name}.json"
        self._state: dict = {}

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def load(self) -> dict | None:
        """Load checkpoint from disk. Returns None if no checkpoint exists."""
        if not self._path.exists():
            return None
        try:
            with open(self._path, encoding="utf-8") as f:
                self._state = json.load(f)
            logger.info("Checkpoint loaded from %s (processed=%d)", self._path, self._state.get("processed_count", 0))
            return self._state
        except Exception as exc:
            logger.warning("Failed to load checkpoint: %s", exc)
            return None

    def save(
        self,
        last_processed_url: str,
        processed_count: int,
        doc_type: str,
        date_from: date | None,
        date_to: date | None,
        embedding_model: str,
        embedding_dimensions: int,
        chunk_size: int,
        chunk_overlap: int,
        chunk_strategy: str = "recursive",
    ) -> None:
        """Persist current pipeline state to disk."""
        self._state = {
            "last_processed_url": last_processed_url,
            "processed_count": processed_count,
            "doc_type": doc_type,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "chunk_strategy": chunk_strategy,
        }
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)

    def validate(
        self,
        embedding_model: str,
        embedding_dimensions: int,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        """Raise ValueError if current params differ from checkpoint params.

        This prevents inserting vectors with incompatible dimensions or
        chunk params into an existing table.
        """
        if not self._state:
            return
        mismatches = []
        checks = [
            ("embedding_model", embedding_model),
            ("embedding_dimensions", embedding_dimensions),
            ("chunk_size", chunk_size),
            ("chunk_overlap", chunk_overlap),
        ]
        for key, current_value in checks:
            saved = self._state.get(key)
            if saved is not None and saved != current_value:
                mismatches.append(f"  {key}: checkpoint={saved!r}, current={current_value!r}")
        if mismatches:
            raise ValueError(
                "Cannot resume: run parameters differ from checkpoint.\n"
                + "\n".join(mismatches)
                + "\nDelete the checkpoint file to start a fresh run."
            )

    def delete(self) -> None:
        """Remove the checkpoint file."""
        if self._path.exists():
            os.remove(self._path)
            logger.info("Checkpoint deleted: %s", self._path)
