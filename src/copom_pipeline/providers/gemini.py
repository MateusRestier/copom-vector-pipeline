"""Google Gemini embedding provider.

Uses the current google-genai SDK (google.genai), which replaced the
deprecated google-generativeai package.

Model: text-embedding-004 (768 dimensions, multilingual, supports Portuguese).

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
    """Embedding provider backed by the Google Gemini API (google-genai SDK)."""

    _DEFAULT_MODEL = "models/text-embedding-004"
    _DIMENSIONS = 768

    def __init__(self) -> None:
        from google import genai  # type: ignore

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set it in your .env file before running the pipeline."
            )
        self._client = genai.Client(api_key=api_key)
        self._model = os.environ.get("GEMINI_EMBEDDING_MODEL", self._DEFAULT_MODEL)

    def embed_text(self, text: str) -> list[float]:
        result = self._client.models.embed_content(
            model=self._model,
            contents=text,
        )
        return list(result.embeddings[0].values)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            result = self._client.models.embed_content(
                model=self._model,
                contents=texts,
            )
            return [list(e.values) for e in result.embeddings]
        except Exception:
            return [self.embed_text(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMENSIONS
