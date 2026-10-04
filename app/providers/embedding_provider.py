"""
Abstract EmbeddingProvider interface.

All embedding models (SentenceTransformer, OpenAI, Gemini, Ollama) implement this interface.
The MemoryManager and VectorStore use ONLY this interface — never a specific model directly.

Interface:
- embed(text) -> list[float]       : Embed a single text
- embed_batch(texts) -> list[list] : Embed multiple texts at once
- embed_query(query) -> list[float]: Embed a search query (may differ from doc embedding)
- dimension -> int                 : Embedding vector dimension
- model_name -> str                : Name of the active model
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EmbeddingProviderError(Exception):
    """Base exception for embedding provider errors."""
    pass


class EmbeddingDimensionError(EmbeddingProviderError):
    """Raised when embedding dimension mismatch occurs."""
    pass


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding models.

    All embedding backends must implement these methods.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the active embedding model."""
        pass

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the embedding model (download, load, etc.)."""
        pass

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text string into a vector.

        Args:
            text: input text to embed

        Returns:
            list of floats representing the embedding vector

        Raises:
            EmbeddingProviderError: on embedding failure
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts at once.

        More efficient than calling embed() repeatedly.

        Args:
            texts: list of input texts

        Returns:
            list of embedding vectors (same order as input)
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a search query.

        Some models use different instructions for queries vs documents.
        Default implementation calls embed().

        Args:
            query: search query text

        Returns:
            embedding vector
        """
        pass

    @abstractmethod
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec1: first embedding vector
            vec2: second embedding vector

        Returns:
            similarity score between 0 and 1
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the provider."""
        pass

