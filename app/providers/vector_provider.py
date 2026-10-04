"""
Abstract VectorProvider interface.

All vector database backends (FAISS, Chroma, Pinecone, Weaviate) implement this interface.
The MemoryManager never talks directly to any vector DB — only through this interface.

Interface:
- add(entries)                      : Add vectors with metadata
- delete(ids)                       : Delete vectors by ID
- update(id, vector, metadata)      : Update existing vector
- search(query_vector, k, filter)   : Search for similar vectors
- count() -> int                    : Total vector count
- rebuild()                         : Rebuild index from scratch
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VectorProviderError(Exception):
    """Base exception for vector provider errors."""
    pass


# ---------------------------------------------------------------------------
# Search result
# ---------------------------------------------------------------------------


@dataclass
class VectorSearchResult:
    """Result from a vector similarity search."""

    id: str
    score: float  # Similarity score (0-1, higher = more similar)
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: Optional[list[float]] = None


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------


class VectorProvider(ABC):
    """Abstract interface for vector database backends.

    All vector DB implementations must implement these methods.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimension this index was built with."""
        pass

    @property
    @abstractmethod
    def size(self) -> int:
        """Return the number of vectors in the index."""
        pass

    @abstractmethod
    def initialize(self, dimension: int) -> None:
        """Initialize the vector index.

        Args:
            dimension: embedding vector dimension
        """
        pass

    @abstractmethod
    def add(self, entries: list[dict]) -> None:
        """Add vectors with metadata to the index.

        Each entry dict must have:
            - 'id': str (unique identifier)
            - 'vector': list[float] (embedding)
            - 'metadata': dict (optional, additional data)

        Args:
            entries: list of entry dicts with id, vector, metadata
        """
        pass

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Delete vectors by their IDs.

        Args:
            ids: list of vector IDs to delete
        """
        pass

    @abstractmethod
    def update(self, id: str, vector: Optional[list[float]] = None, metadata: Optional[dict] = None) -> bool:
        """Update an existing vector or its metadata.

        Args:
            id: vector ID to update
            vector: new embedding vector (None = keep existing)
            metadata: new metadata (None = keep existing)

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        k: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Search for k most similar vectors.

        Args:
            query_vector: query embedding vector
            k: number of results to return
            filter: optional metadata filter (provider-specific)

        Returns:
            list of VectorSearchResult sorted by similarity (descending)
        """
        pass

    @abstractmethod
    def search_by_id(
        self,
        id: str,
        k: int = 10,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using an existing vector's ID.

        Args:
            id: ID of the reference vector
            k: number of results to return

        Returns:
            list of VectorSearchResult sorted by similarity (descending)
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Return the total number of vectors in the index."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all vectors from the index."""
        pass

    @abstractmethod
    def rebuild(self) -> None:
        """Rebuild the index from scratch.

        Called after significant updates to optimize search performance.
        """
        pass

    @abstractmethod
    def save(self, path: str) -> None:
        """Persist the index to disk.

        Args:
            path: file path to save the index
        """
        pass

    @abstractmethod
    def load(self, path: str) -> bool:
        """Load a previously saved index from disk.

        Args:
            path: file path to load from

        Returns:
            True if loaded successfully
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Release resources and close the index."""
        pass

