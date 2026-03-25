"""Google Gemini embedding provider.

Model: text-embedding-004 (768 dimensions, multilingual, supports Portuguese).

To switch to a different Gemini embedding model, set GEMINI_EMBEDDING_MODEL
in your .env file.  Update EMBEDDING_DIMENSIONS accordingly.

Required env vars:
    GEMINI_API_KEY          — your Google AI API key
    GEMINI_EMBEDDING_MODEL  — (optional) defaults to models/text-embedding-004
"""

from __future__ import annotations

import os

from copom_pipeline.providers.base import EmbeddingProvider
from copom_pipeline.providers.factory import register_embedding_provider


@register_embedding_provider("gemini")
class GeminiEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Google Gemini API."""

    _DEFAULT_MODEL = "models/text-embedding-004"
    _DIMENSIONS = 768

    def __init__(self) -> None:
        # Lazy import: google-generativeai is only loaded when this provider
        # is instantiated, not at module import time.
        import google.generativeai as genai  # type: ignore

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set it in your .env file before running the pipeline."
            )
        genai.configure(api_key=api_key)
        self._genai = genai
        self._model = os.environ.get("GEMINI_EMBEDDING_MODEL", self._DEFAULT_MODEL)

    # ──────────────────────────────────────────────────────────────────
    #  EmbeddingProvider interface
    # ──────────────────────────────────────────────────────────────────

    def embed_text(self, text: str) -> list[float]:
        """Embed a single string and return its vector."""
        result = self._genai.embed_content(
            model=self._model,
            content=text,
            task_type="retrieval_document",
        )
        return result["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings using Gemini's batch endpoint.

        Falls back to sequential calls if the batch API is unavailable.
        """
        if not texts:
            return []
        try:
            result = self._genai.embed_content(
                model=self._model,
                content=texts,
                task_type="retrieval_document",
            )
            embeddings = result["embedding"]
            # Gemini returns a flat list for a single item, list-of-lists for batch.
            if texts and isinstance(embeddings[0], float):
                return [embeddings]
            return embeddings
        except Exception:
            # Fallback: embed one-by-one
            return [self.embed_text(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMENSIONS
