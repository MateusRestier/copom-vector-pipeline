"""Provider registry and factory for embedding providers.

The registry-decorator pattern used here means that adding a new provider
requires only:
  1. Creating the provider class in its own module.
  2. Decorating it with @register_embedding_provider("name").
  3. Importing that module below in _load_providers().

The factory (get_embedding_provider) is never edited when adding providers.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copom_pipeline.providers.base import EmbeddingProvider

_REGISTRY: dict[str, type["EmbeddingProvider"]] = {}


def register_embedding_provider(name: str):
    """Class decorator that registers an EmbeddingProvider implementation.

    Usage:
        @register_embedding_provider("gemini")
        class GeminiEmbeddingProvider(EmbeddingProvider): ...
    """
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator


def _load_providers() -> None:
    """Import all provider modules so their decorators execute."""
    # Add new provider imports here — one line per provider.
    from copom_pipeline.providers import gemini  # noqa: F401


def get_embedding_provider(provider_name: str | None = None) -> "EmbeddingProvider":
    """Instantiate and return the embedding provider selected by env var.

    Args:
        provider_name: Override the provider name.  If None, reads
            EMBEDDING_PROVIDER from the environment (default: "gemini").

    Raises:
        ValueError: If the requested provider is not registered.
    """
    _load_providers()
    name = provider_name or os.environ.get("EMBEDDING_PROVIDER", "gemini")
    if name not in _REGISTRY:
        available = list(_REGISTRY.keys())
        raise ValueError(
            f"Unknown embedding provider '{name}'. "
            f"Available providers: {available}. "
            f"Check your EMBEDDING_PROVIDER environment variable."
        )
    return _REGISTRY[name]()
