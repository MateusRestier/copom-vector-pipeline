"""Abstract base classes for pluggable embedding providers.

To add a new provider:
1. Create a new file in this package (e.g. openai.py).
2. Subclass EmbeddingProvider and implement all abstract methods.
3. Decorate the class with @register_embedding_provider("your-name").
4. Import the module in factory.py so the decorator runs at startup.
5. Set EMBEDDING_PROVIDER=your-name in .env — no other changes needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Interface every embedding provider must satisfy."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a single text string."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of text strings.

        Implementations should use the provider's native batch API when
        available to reduce latency and API call overhead.
        """
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of vectors produced by this provider.

        This value is read at schema-creation time to set the pgvector
        column type (e.g. vector(768)).  It must match the actual model.
        """
        ...
