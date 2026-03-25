"""Google Gemini embedding provider.

Uses the current google-genai SDK (google.genai), which replaced the
deprecated google-generativeai package.

Model: gemini-embedding-001 (output truncated to 1536 dims via output_dimensionality).
Native dimensionality is 3072, but pgvector's HNSW index is capped at 2000 dims, so
we truncate to 1536 (still within the HNSW limit and retains high retrieval quality).

Required env vars:
    GEMINI_API_KEY              — your Google AI API key
    GEMINI_EMBEDDING_MODEL      — (optional) defaults to models/gemini-embedding-001
    EMBEDDING_DIMENSIONS        — (optional) output dims, defaults to 1536
"""

from __future__ import annotations

import os

from copom_pipeline.providers.base import EmbeddingProvider
from copom_pipeline.providers.factory import register_embedding_provider


@register_embedding_provider("gemini")
class GeminiEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Google Gemini API (google-genai SDK)."""

    _DEFAULT_MODEL = "models/gemini-embedding-001"
    _DEFAULT_DIMENSIONS = 1536

    def __init__(self) -> None:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set it in your .env file before running the pipeline."
            )
        self._client = genai.Client(api_key=api_key)
        self._model = os.environ.get("GEMINI_EMBEDDING_MODEL", self._DEFAULT_MODEL)
        self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", str(self._DEFAULT_DIMENSIONS)))
        self._embed_config = genai_types.EmbedContentConfig(output_dimensionality=self._dimensions)

    def embed_text(self, text: str) -> list[float]:
        result = self._client.models.embed_content(
            model=self._model,
            contents=text,
            config=self._embed_config,
        )
        return list(result.embeddings[0].values)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            result = self._client.models.embed_content(
                model=self._model,
                contents=texts,
                config=self._embed_config,
            )
            return [list(e.values) for e in result.embeddings]
        except Exception:
            return [self.embed_text(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._dimensions
