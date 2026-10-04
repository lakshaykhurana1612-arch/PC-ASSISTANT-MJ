"""
Abstract MemoryProvider interface.

All storage backends (SQLite, PostgreSQL, MongoDB, Cloud) implement this interface.
The MemoryManager never talks directly to any storage backend — only through this interface.

Interface:
- create(entry) -> str          : Store a new memory, return ID
- read(memory_id) -> MemoryEntry : Retrieve by ID
- update(memory_id, data) -> bool : Update existing memory
- delete(memory_id) -> bool      : Soft or hard delete
- search(query) -> list         : Search by query/filter
- list(filter) -> list          : List memories with filter
- count(filter) -> int          : Count matching memories
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MemoryProviderError(Exception):
    """Base exception for memory provider errors."""
    pass


class MemoryNotFoundError(MemoryProviderError):
    """Raised when a memory ID is not found."""
    pass


class MemoryDuplicateError(MemoryProviderError):
    """Raised when a duplicate memory is detected."""
    pass


# ---------------------------------------------------------------------------
# Filter for queries
# ---------------------------------------------------------------------------


@dataclass
class MemoryFilter:
    """Filter criteria for memory queries."""

    memory_type: Optional[str] = None
    importance_min: float = 0.0
    importance_max: float = 1.0
    tags: list[str] = field(default_factory=list)
    created_after: Optional[float] = None
    created_before: Optional[float] = None
    source: Optional[str] = None
    pinned_only: bool = False
    archived: bool = False
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"  # created_at, importance, last_accessed
    sort_desc: bool = True


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------


class MemoryProvider(ABC):
    """Abstract interface for memory storage backends.

    All memory providers must implement these methods.
    The MemoryManager calls ONLY these methods — never backend-specific APIs.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the storage backend (create tables, connect, etc.)."""
        pass

    @abstractmethod
    def create(self, entry: dict) -> str:
        """Store a new memory entry.

        Args:
            entry: dict with fields from MemoryEntry schema

        Returns:
            str: unique memory ID

        Raises:
            MemoryDuplicateError: if duplicate detected
            MemoryProviderError: on storage failure
        """
        pass

    @abstractmethod
    def read(self, memory_id: str) -> Optional[dict]:
        """Retrieve a memory by its ID.

        Args:
            memory_id: unique memory identifier

        Returns:
            dict with memory data, or None if not found
        """
        pass

    @abstractmethod
    def update(self, memory_id: str, data: dict) -> bool:
        """Update an existing memory entry.

        Args:
            memory_id: unique memory identifier
            data: dict of fields to update

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    def delete(self, memory_id: str, permanent: bool = False) -> bool:
        """Delete a memory entry.

        Args:
            memory_id: unique memory identifier
            permanent: if True, hard delete; if False, soft delete (archive)

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def search(self, query: str, filter: Optional[MemoryFilter] = None) -> list[dict]:
        """Search memories by text query.

        Args:
            query: natural language or keyword search string
            filter: optional filter criteria

        Returns:
            list of matching memory dicts (up to filter.limit)
        """
        pass

    @abstractmethod
    def list(self, filter: MemoryFilter) -> list[dict]:
        """List memories with optional filtering.

        Args:
            filter: filter criteria (type, importance, tags, etc.)

        Returns:
            list of matching memory dicts
        """
        pass

    @abstractmethod
    def count(self, filter: MemoryFilter) -> int:
        """Count memories matching filter.

        Args:
            filter: filter criteria

        Returns:
            count of matching memories
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all memories (use with caution)."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the storage backend (release connections, files)."""
        pass

    @abstractmethod
    def health_check(self) -> dict:
        """Check if the storage backend is healthy.

        Returns:
            dict with 'status' (ok/error) and optional 'details'
        """
        pass

