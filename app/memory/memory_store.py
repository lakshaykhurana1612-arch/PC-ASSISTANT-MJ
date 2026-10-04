"""
Memory Store — Unified storage layer.

Routes memory operations to the appropriate storage backends:
- MemoryProvider (SQLite) for persistent CRUD
- VectorProvider (FAISS) for vector search
- In-memory cache for hot memories

This is the ONLY layer that coordinates between multiple backends.
The MemoryManager calls this layer; never the providers directly.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.memory.models import MemoryEntry, MemoryQuery, MemoryResult, MemoryType
from app.memory.memory_search import MemorySearch
from app.memory.importance_scorer import ImportanceScorer
from app.providers.memory_provider import (
    MemoryProvider,
    MemoryFilter,
    MemoryDuplicateError,
    MemoryNotFoundError,
)
from app.providers.embedding_provider import EmbeddingProvider
from app.providers.vector_provider import VectorProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-Memory Cache
# ---------------------------------------------------------------------------


class LRUCache:
    """Simple LRU cache for hot memories."""

    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self._cache: dict[str, MemoryEntry] = {}
        self._order: list[str] = []

    def get(self, key: str) -> Optional[MemoryEntry]:
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: MemoryEntry) -> None:
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self.capacity:
            oldest = self._order.pop(0)
            self._cache.pop(oldest, None)

        self._cache[key] = value
        self._order.append(key)

    def remove(self, key: str) -> None:
        self._cache.pop(key, None)
        if key in self._order:
            self._order.remove(key)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


# ---------------------------------------------------------------------------
# Memory Store
# ---------------------------------------------------------------------------


class MemoryStore:
    """Unified storage layer coordinating SQLite + FAISS + Cache.

    This is the ONLY class that talks to multiple providers.
    All other code uses MemoryManager → which uses this store.

    Usage:
        store = MemoryStore(memory_provider, embedding_provider, vector_provider)
        mid = store.create(entry)
        results = store.search(query)
    """

    def __init__(
        self,
        memory_provider: MemoryProvider,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_provider: Optional[VectorProvider] = None,
        cache_capacity: int = 100,
    ):
        self.memory_provider = memory_provider
        self.embedding_provider = embedding_provider
        self.vector_provider = vector_provider
        self.cache = LRUCache(capacity=cache_capacity)

        # Search engine
        self.search_engine = MemorySearch(
            memory_provider=memory_provider,
            embedding_provider=embedding_provider,
            vector_provider=vector_provider,
        )

        # Importance scorer
        self.importance_scorer = ImportanceScorer()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, entry: MemoryEntry, auto_embed: bool = True) -> str:
        """Store a new memory entry.

        Args:
            entry: MemoryEntry to store
            auto_embed: whether to auto-generate embedding and vector index

        Returns:
            str: memory ID
        """
        now = time.time()

        # Set timestamps if not set
        if not entry.created_at:
            entry.created_at = now
        if not entry.updated_at:
            entry.updated_at = now
        if not entry.accessed_at:
            entry.accessed_at = now

        # Compute importance if not set
        if not entry.importance or entry.importance == 0.5:
            entry.importance = self.importance_scorer.calculate(entry)
            entry.importance_factors = self.importance_scorer.get_factors(entry).__dict__

        # Convert to dict for storage
        entry_dict = entry.to_dict()

        # Store in SQLite
        try:
            memory_id = self.memory_provider.create(entry_dict)
            entry.id = memory_id
        except MemoryDuplicateError:
            logger.warning(f"Duplicate memory, updating instead")
            self.memory_provider.update(entry.id, entry_dict)
            memory_id = entry.id

        # Auto-generate embedding and store in vector index
        if auto_embed and self.embedding_provider and self.vector_provider:
            self._store_embedding(entry)

        # Update cache
        self.cache.set(memory_id, entry)

        return memory_id

    def read(self, memory_id: str) -> Optional[MemoryEntry]:
        """Retrieve a memory by ID."""
        # Check cache first
        cached = self.cache.get(memory_id)
        if cached:
            return cached

        # Fetch from SQLite
        entry_dict = self.memory_provider.read(memory_id)
        if entry_dict is None:
            return None

        entry = MemoryEntry.from_dict(entry_dict)

        # Update cache
        self.cache.set(memory_id, entry)

        return entry

    def update(self, memory_id: str, data: dict) -> bool:
        """Update an existing memory.

        Args:
            memory_id: memory ID to update
            data: dict of fields to update

        Returns:
            True if updated
        """
        data["updated_at"] = time.time()

        # Update in SQLite
        success = self.memory_provider.update(memory_id, data)

        if success:
            # Update cache
            cached = self.cache.get(memory_id)
            if cached:
                for k, v in data.items():
                    if hasattr(cached, k):
                        setattr(cached, k, v)
                self.cache.set(memory_id, cached)

            # Regenerate embedding if content changed
            if "content" in data or "title" in data:
                entry = self.read(memory_id)
                if entry and self.embedding_provider and self.vector_provider:
                    self._store_embedding(entry)

        return success

    def delete(self, memory_id: str, permanent: bool = False) -> bool:
        """Delete a memory.

        Args:
            memory_id: memory ID to delete
            permanent: if True, hard delete; if False, archive

        Returns:
            True if deleted
        """
        success = self.memory_provider.delete(memory_id, permanent=permanent)

        if success:
            # Remove from cache
            self.cache.remove(memory_id)

            # Remove from vector index
            if self.vector_provider:
                try:
                    self.vector_provider.delete([memory_id])
                except Exception as e:
                    logger.warning(f"Failed to remove from vector index: {e}")

        return success

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: MemoryQuery) -> list[MemoryResult]:
        """Search memories using hybrid search.

        Args:
            query: MemoryQuery with search parameters

        Returns:
            ranked list of MemoryResult
        """
        return self.search_engine.search(query)

    def list_by_filter(self, filter: MemoryFilter) -> list[MemoryEntry]:
        """List memories by filter criteria."""
        entries = self.memory_provider.list(filter)
        return [MemoryEntry.from_dict(e) for e in entries]

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _store_embedding(self, entry: MemoryEntry) -> None:
        """Generate and store embedding for a memory entry."""
        try:
            text_to_embed = f"{entry.title} {entry.content} {entry.summary}"
            if not text_to_embed.strip():
                text_to_embed = entry.content

            if not text_to_embed.strip():
                return

            # Truncate to prevent excessive embedding time
            text_to_embed = text_to_embed[:2048]

            embedding = self.embedding_provider.embed(text_to_embed)
            if not embedding:
                return

            entry.embedding = embedding

            # Store in vector index
            vec_entry = {
                "id": entry.id,
                "vector": embedding,
                "metadata": {
                    "memory_type": entry.memory_type,
                    "title": entry.title[:100],
                    "importance": entry.importance,
                    "tags": entry.tags,
                },
            }

            self.vector_provider.add([vec_entry])

        except Exception as e:
            logger.warning(f"Failed to store embedding: {e}")

    def regenerate_embeddings(self, memory_type: Optional[str] = None) -> int:
        """Regenerate embeddings for all memories or a specific type.

        Args:
            memory_type: optional filter by memory type

        Returns:
            number of embeddings regenerated
        """
        if not self.embedding_provider or not self.vector_provider:
            return 0

        mfilter = MemoryFilter(limit=10000)
        if memory_type:
            mfilter.memory_type = memory_type

        entries = self.memory_provider.list(mfilter)
        count = 0

        for entry_dict in entries:
            entry = MemoryEntry.from_dict(entry_dict)
            self._store_embedding(entry)
            count += 1

        logger.info(f"Regenerated {count} embeddings")
        return count

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def count(self, memory_type: Optional[str] = None) -> int:
        """Count memories, optionally by type."""
        mfilter = MemoryFilter()
        if memory_type:
            mfilter.memory_type = memory_type
        return self.memory_provider.count(mfilter)

    def clear(self) -> None:
        """Clear all memories."""
        self.memory_provider.clear()
        if self.vector_provider:
            self.vector_provider.clear()
        self.cache.clear()
        logger.warning("All memory stores cleared.")

    def close(self) -> None:
        """Close all providers."""
        self.cache.clear()
        self.memory_provider.close()
        if self.vector_provider:
            self.vector_provider.close()
        if self.embedding_provider:
            self.embedding_provider.close()
        logger.info("Memory stores closed.")

