"""
Memory Manager — Single public API for all memory operations.

All memory operations go through this manager. No other code talks
directly to providers, stores, or search engines.

Public API:
    remember()    — Store a new memory
    recall()      — Retrieve a memory by ID
    search()      — Hybrid search across all memories
    update()      — Update an existing memory
    forget()      — Delete a memory
    pin()         — Pin a memory (prevent auto-delete)
    archive()     — Archive a memory
    summarize()   — Generate/update summary
    cleanup()     — Run maintenance
    merge()       — Merge two memories together
    list()        — List memories by filter
    count()       — Count memories
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.memory.models import (
    MemoryEntry,
    MemoryQuery,
    MemoryResult,
    MemoryType,
    MemorySource,
    Importance,
)
from app.memory.memory_store import MemoryStore
from app.memory.memory_search import MemorySearch
from app.memory.memory_cleaner import MemoryCleaner
from app.memory.memory_observer import MemoryObserver
from app.memory.memory_metrics import MemoryMetrics
from app.memory.memory_serializer import MemorySerializer
from app.memory.importance_scorer import ImportanceScorer
from app.providers.memory_provider import (
    MemoryProvider,
    MemoryFilter,
    MemoryNotFoundError,
)
from app.providers.embedding_provider import EmbeddingProvider
from app.providers.vector_provider import VectorProvider
from app.events.event_bus import get_event_bus
from app.memory.memory_events import (
    MemoryCreatedEvent,
    MemoryUpdatedEvent,
    MemoryDeletedEvent,
    MemoryAccessedEvent,
    MemorySearchEvent,
    MemoryErrorEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory Manager Configuration
# ---------------------------------------------------------------------------


@dataclass
class MemoryManagerConfig:
    """Configuration for the Memory Manager."""

    # Auto-saving
    auto_embed: bool = True
    auto_observe: bool = True      # Start observer automatically
    auto_cleanup: bool = True      # Start auto-cleanup
    cleanup_interval_minutes: float = 60.0

    # Limits
    max_search_results: int = 20
    max_recall_context: int = 5    # Memories to inject into LLM context

    # Storage
    sqlite_path: Optional[str] = None
    faiss_path: Optional[str] = None
    vector_dimension: int = 384
    cache_capacity: int = 200

    # Behavior
    save_conversations: bool = True
    learn_preferences: bool = True
    track_metrics: bool = True


# ---------------------------------------------------------------------------
# Memory Manager — The Single Public API
# ---------------------------------------------------------------------------


class MemoryManager:
    """Central memory manager — single public API for ALL memory operations.

    Usage:
        mgr = MemoryManager(memory_provider, embedding_provider, vector_provider)

        # Store
        entry = MemoryEntry(title="Resume file location", content="D:/docs/resume.pdf")
        mem_id = mgr.remember(entry)

        # Retrieve
        entry = mgr.recall(mem_id)

        # Search
        results = mgr.search("resume file for rahul")

        # Update
        mgr.update(mem_id, {"title": "Updated title"})

        # Delete
        mgr.forget(mem_id)
    """

    def __init__(
        self,
        memory_provider: MemoryProvider,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_provider: Optional[VectorProvider] = None,
        config: Optional[MemoryManagerConfig] = None,
    ):
        self.config = config or MemoryManagerConfig()

        # Core store
        self.store = MemoryStore(
            memory_provider=memory_provider,
            embedding_provider=embedding_provider,
            vector_provider=vector_provider,
            cache_capacity=self.config.cache_capacity,
        )

        # Search engine (wraps store's search)
        self.search_engine = self.store.search_engine

        # Cleaner
        self.cleaner = MemoryCleaner(self, config=None)

        # Observer
        self.observer = MemoryObserver(self, config=None)

        # Metrics
        if self.config.track_metrics:
            self.metrics = MemoryMetrics.get_instance()
        else:
            self.metrics = None

        # Scorer
        self.scorer = ImportanceScorer()

        # Serializer
        self.serializer = MemorySerializer()

        # Event bus
        self._event_bus = get_event_bus()

        # Auto-observe
        if self.config.auto_observe:
            self.observer.start()

        # Auto-cleanup
        if self.config.auto_cleanup:
            self.cleaner.start_auto_cleanup()

    # ======================================================================
    # PUBLIC API — CRUD
    # ======================================================================

    def remember(
        self,
        entry: MemoryEntry,
        auto_embed: Optional[bool] = None,
    ) -> str:
        """Store a new memory.

        This is the primary "create" operation. Always use this instead
        of calling store.create() directly.

        Args:
            entry: MemoryEntry to store
            auto_embed: whether to auto-generate embedding (default: config.auto_embed)

        Returns:
            str: assigned memory ID
        """
        start = time.time()
        embed = auto_embed if auto_embed is not None else self.config.auto_embed

        try:
            memory_id = self.store.create(entry, auto_embed=embed)

            # Emit event
            self._emit(MemoryCreatedEvent(
                memory_id=memory_id,
                memory_type=entry.memory_type,
                importance=entry.importance,
                source=entry.source,
                title=entry.title,
                has_embedding=embed,
            ))

            # Track metrics
            if self.metrics:
                latency = (time.time() - start) * 1000
                self.metrics.record_operation("create", latency)

            return memory_id

        except Exception as e:
            logger.error(f"Failed to remember: {e}")
            self._emit(MemoryErrorEvent(operation="create", error_message=str(e)))
            raise

    def recall(self, memory_id: str) -> Optional[MemoryEntry]:
        """Retrieve a memory by its ID.

        Args:
            memory_id: unique memory identifier

        Returns:
            MemoryEntry or None if not found
        """
        start = time.time()

        try:
            entry = self.store.read(memory_id)

            if entry:
                self._emit(MemoryAccessedEvent(memory_id=memory_id, access_type="read"))

            if self.metrics:
                latency = (time.time() - start) * 1000
                self.metrics.record_operation("read", latency)

            return entry

        except Exception as e:
            logger.error(f"Failed to recall {memory_id}: {e}")
            self._emit(MemoryErrorEvent(operation="read", error_message=str(e), memory_id=memory_id))
            return None

    def update(self, memory_id: str, data: dict) -> bool:
        """Update an existing memory.

        Args:
            memory_id: memory ID to update
            data: dict of fields to update (e.g., {"title": "New title", "content": "..."})

        Returns:
            True if updated successfully
        """
        start = time.time()

        try:
            success = self.store.update(memory_id, data)

            if success:
                self._emit(MemoryUpdatedEvent(
                    memory_id=memory_id,
                    fields_updated=list(data.keys()),
                ))

            if self.metrics:
                latency = (time.time() - start) * 1000
                self.metrics.record_operation("update", latency)

            return success

        except Exception as e:
            logger.error(f"Failed to update {memory_id}: {e}")
            self._emit(MemoryErrorEvent(operation="update", error_message=str(e), memory_id=memory_id))
            return False

    def forget(self, memory_id: str, permanent: bool = False) -> bool:
        """Delete/archive a memory.

        Args:
            memory_id: memory ID to delete
            permanent: if True, hard delete; if False, soft delete (archive)

        Returns:
            True if deleted
        """
        start = time.time()

        try:
            success = self.store.delete(memory_id, permanent=permanent)

            if success:
                self._emit(MemoryDeletedEvent(
                    memory_id=memory_id,
                    permanent=permanent,
                ))

            if self.metrics:
                latency = (time.time() - start) * 1000
                self.metrics.record_operation("delete", latency)

            return success

        except Exception as e:
            logger.error(f"Failed to forget {memory_id}: {e}")
            self._emit(MemoryErrorEvent(operation="delete", error_message=str(e), memory_id=memory_id))
            return False

    # ======================================================================
    # PUBLIC API — Search & Query
    # ======================================================================

    def search(
        self,
        text: str = "",
        memory_type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
        min_score: float = 0.2,
        include_archived: bool = False,
    ) -> list[MemoryResult]:
        """Hybrid search across all memories.

        This is the primary search method. It combines:
        - Semantic search (vector similarity)
        - Keyword search (SQLite LIKE)
        - Importance scoring
        - Recency scoring

        Args:
            text: search query text
            memory_type: filter by memory type (e.g., "CONVERSATION", "PREFERENCE")
            tags: filter by tags
            limit: max results to return
            min_score: minimum relevance score (0-1)
            include_archived: whether to include archived memories

        Returns:
            list of MemoryResult sorted by relevance (highest first)
        """
        start = time.time()

        query = MemoryQuery(
            text=text,
            memory_type=memory_type,
            tags=tags or [],
            limit=min(limit, self.config.max_search_results),
            min_score=min_score,
        )

        try:
            results = self.store.search(query)

            if self.metrics:
                elapsed = (time.time() - start) * 1000
                self.metrics.record_search(len(results), elapsed)

            self._emit(MemorySearchEvent(
                query=text,
                result_count=len(results),
                search_time_ms=elapsed if self.metrics else 0,
            ))

            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            self._emit(MemoryErrorEvent(operation="search", error_message=str(e)))
            return []

    def list(self, filter: Optional[MemoryFilter] = None) -> list[MemoryEntry]:
        """List memories by filter criteria.

        Args:
            filter: MemoryFilter with criteria (type, importance, tags, etc.)

        Returns:
            list of MemoryEntry
        """
        if filter is None:
            filter = MemoryFilter(limit=50)
        return self.store.list_by_filter(filter)

    def count(self, memory_type: Optional[str] = None) -> int:
        """Count memories, optionally by type.

        Args:
            memory_type: filter by MemoryType name

        Returns:
            count of matching memories
        """
        return self.store.count(memory_type=memory_type)

    # ======================================================================
    # PUBLIC API — Memory Management
    # ======================================================================

    def pin(self, memory_id: str) -> bool:
        """Pin a memory — prevents auto-deletion and increases importance.

        Args:
            memory_id: memory ID to pin

        Returns:
            True if pinned
        """
        return self.update(memory_id, {"pinned": True, "importance": 1.0})

    def unpin(self, memory_id: str) -> bool:
        """Unpin a memory.

        Args:
            memory_id: memory ID to unpin
        """
        return self.update(memory_id, {"pinned": False})

    def archive(self, memory_id: str) -> bool:
        """Archive a memory (soft-delete, can be restored).

        Args:
            memory_id: memory ID to archive
        """
        return self.update(memory_id, {"archived": True})

    def restore(self, memory_id: str) -> bool:
        """Restore an archived memory.

        Args:
            memory_id: memory ID to restore
        """
        return self.update(memory_id, {"archived": False})

    def summarize(self, memory_id: str, summary: Optional[str] = None) -> bool:
        """Generate or update a memory's summary.

        Args:
            memory_id: memory ID
            summary: new summary text. If None, auto-generate from content.

        Returns:
            True if updated
        """
        entry = self.recall(memory_id)
        if not entry:
            return False

        if summary:
            return self.update(memory_id, {"summary": summary})

        # Auto-generate summary from content
        if entry.content:
            auto_summary = entry.content[:300]
            if len(entry.content) > 300:
                auto_summary += "..."
            return self.update(memory_id, {"summary": auto_summary})

        return False

    def merge(self, target_id: str, source_ids: list[str], delete_source: bool = True) -> Optional[str]:
        """Merge multiple memories into one.

        Merges content, tags, and metadata from source memories into the target.
        Optionally deletes source memories after merge.

        Args:
            target_id: ID of the target memory to merge into
            source_ids: IDs of source memories to merge
            delete_source: whether to delete source memories after merge

        Returns:
            target_id if successful, None on failure
        """
        target = self.recall(target_id)
        if not target:
            logger.warning(f"Target memory {target_id} not found")
            return None

        for src_id in source_ids:
            source = self.recall(src_id)
            if not source:
                continue

            # Merge content
            if source.content and source.content not in target.content:
                target.content += f"\n\n---\n{source.content}"

            # Merge tags
            for tag in source.tags:
                if tag not in target.tags:
                    target.tags.append(tag)

            # Merge metadata
            target.metadata.update(source.metadata)

            # Update related_ids
            if src_id not in target.related_ids:
                target.related_ids.append(src_id)

            # Delete source
            if delete_source:
                self.forget(src_id, permanent=True)

        # Save updated target
        self.update(target_id, {
            "content": target.content,
            "tags": target.tags,
            "metadata": target.metadata,
            "related_ids": target.related_ids,
        })

        return target_id

    # ======================================================================
    # PUBLIC API — Maintenance
    # ======================================================================

    def cleanup(self) -> dict[str, int]:
        """Run memory maintenance: archive, compress, summarize, delete.

        Returns:
            dict with counts per operation
        """
        stats = self.cleaner.cleanup(full=True)

        if self.metrics:
            self.metrics.record_cleanup(
                archived=stats.get("archived", 0),
                deleted=stats.get("deleted", 0),
                compressed=stats.get("compressed", 0),
            )

        return stats

    # ======================================================================
    # PUBLIC API — Context for LLM
    # ======================================================================

    def get_context_for_llm(self, user_input: str, max_memories: int = 5) -> str:
        """Get relevant memories formatted as context for LLM prompt.

        This is the method called by ContextBuilder to inject memory
        into the LLM prompt.

        Args:
            user_input: current user input to find relevant memories for
            max_memories: max memories to include

        Returns:
            formatted string with relevant memories for the prompt
        """
        if not user_input:
            return ""

        results = self.search(
            text=user_input,
            limit=self.config.max_recall_context,
            min_score=0.3,
        )

        if not results:
            return ""

        return MemorySerializer.batch_summarize_for_llm(
            [r.entry for r in results],
            max_entries=max_memories,
        )

    # ======================================================================
    # PUBLIC API — Lifecycle
    # ======================================================================

    def initialize(self) -> None:
        """Initialize all providers and load existing data."""
        self.store.memory_provider.initialize()
        if self.store.embedding_provider:
            self.store.embedding_provider.initialize()
        if self.store.vector_provider:
            self.store.vector_provider.initialize(self.config.vector_dimension)

        # Start auto-services
        if self.config.auto_observe:
            self.observer.start()
        if self.config.auto_cleanup:
            self.cleaner.start_auto_cleanup()

        logger.info("Memory Manager initialized")

    def close(self) -> None:
        """Shut down all memory services gracefully."""
        self.observer.stop()
        self.cleaner.stop_auto_cleanup()
        self.store.close()
        logger.info("Memory Manager shut down")

    def metrics_report(self) -> str:
        """Get human-readable metrics report."""
        if self.metrics:
            return self.metrics.report(memory_store=self.store)
        return "Metrics tracking is disabled"

    # ======================================================================
    # INTERNAL
    # ======================================================================

    def _emit(self, event) -> None:
        """Emit an event to the event bus."""
        try:
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to emit event: {e}")

    @property
    def provider(self):
        """Access to the underlying MemoryProvider (for advanced use)."""
        return self.store.memory_provider

