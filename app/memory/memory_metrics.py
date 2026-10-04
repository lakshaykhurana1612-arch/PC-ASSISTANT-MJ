"""
Memory Metrics — Track usage and performance metrics.

Records:
- Times retrieved per memory
- Times updated per memory
- Last accessed timestamp
- Source of creation (MJ, user, system, developer)
- Search latency
- Storage size
- Cache hit/miss ratio
- Cleanup stats

Thread-safe for concurrent access.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics data
# ---------------------------------------------------------------------------


@dataclass
class MemoryMetricsSnapshot:
    """Snapshot of memory system metrics."""

    # General stats
    total_memories: int = 0
    total_by_type: dict[str, int] = field(default_factory=dict)
    total_archived: int = 0
    total_pinned: int = 0
    total_deleted: int = 0

    # Performance
    total_operations: int = 0
    operations_by_type: dict[str, int] = field(default_factory=dict)
    average_latency_ms: float = 0.0
    latency_by_operation: dict[str, float] = field(default_factory=dict)

    # Search
    total_searches: int = 0
    average_search_time_ms: float = 0.0
    search_result_avg: float = 0.0

    # Cache
    cache_size: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_ratio: float = 0.0

    # Cleanup
    last_cleanup_time: float = 0.0
    total_archived_by_cleaner: int = 0
    total_deleted_by_cleaner: int = 0
    total_compressed: int = 0

    # Storage
    storage_size_bytes: int = 0
    vector_index_size: int = 0

    # Time period
    uptime_hours: float = 0.0
    start_time: float = 0.0


# ---------------------------------------------------------------------------
# Memory Metrics Collector
# ---------------------------------------------------------------------------


class MemoryMetrics:
    """Collects and reports memory system metrics.

    Thread-safe singleton.

    Usage:
        metrics = MemoryMetrics()
        metrics.record_operation("create", latency_ms=15.2)
        metrics.record_search(n_results=5, time_ms=45.0)
        metrics.record_cache_hit()
        snapshot = metrics.snapshot()
    """

    _instance: Optional["MemoryMetrics"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()

        # Operation counts
        self._total_operations = 0
        self._operations_by_type: Counter = Counter()

        # Latency tracking
        self._latency_total_ms: float = 0.0
        self._latency_by_operation: dict[str, list[float]] = defaultdict(list)

        # Search tracking
        self._total_searches = 0
        self._search_time_total_ms: float = 0.0
        self._search_results_total: int = 0

        # Cache tracking
        self._cache_hits = 0
        self._cache_misses = 0

        # Cleanup tracking
        self._last_cleanup_time: float = 0.0
        self._total_archived = 0
        self._total_deleted = 0
        self._total_compressed = 0

        # Start time
        self._start_time = time.time()

    @classmethod
    def get_instance(cls) -> "MemoryMetrics":
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Record methods
    # ------------------------------------------------------------------

    def record_operation(self, operation: str, latency_ms: float = 0.0) -> None:
        """Record a memory operation.

        Args:
            operation: 'create', 'read', 'update', 'delete', 'search'
            latency_ms: time taken in milliseconds
        """
        with self._lock:
            self._total_operations += 1
            self._operations_by_type[operation] += 1
            self._latency_total_ms += latency_ms
            self._latency_by_operation[operation].append(latency_ms)

    def record_search(self, n_results: int, time_ms: float) -> None:
        """Record a search operation.

        Args:
            n_results: number of results returned
            time_ms: search time in milliseconds
        """
        with self._lock:
            self._total_searches += 1
            self._search_time_total_ms += time_ms
            self._search_results_total += n_results
            self._total_operations += 1
            self._operations_by_type["search"] += 1
            self._latency_total_ms += time_ms
            self._latency_by_operation["search"].append(time_ms)

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        with self._lock:
            self._cache_misses += 1

    def record_cleanup(self, archived: int = 0, deleted: int = 0, compressed: int = 0) -> None:
        """Record cleanup operation.

        Args:
            archived: number of memories archived
            deleted: number of memories deleted
            compressed: number of memories compressed
        """
        with self._lock:
            self._last_cleanup_time = time.time()
            self._total_archived += archived
            self._total_deleted += deleted
            self._total_compressed += compressed

    # ------------------------------------------------------------------
    # Snapshot generation
    # ------------------------------------------------------------------

    def snapshot(
        self,
        memory_store=None,  # Optional MemoryStore for live stats
    ) -> MemoryMetricsSnapshot:
        """Generate a metrics snapshot.

        Args:
            memory_store: optional MemoryStore for live data

        Returns:
            MemoryMetricsSnapshot with current metrics
        """
        now = time.time()
        uptime = (now - self._start_time) / 3600

        with self._lock:
            snapshot = MemoryMetricsSnapshot(
                total_operations=self._total_operations,
                operations_by_type=dict(self._operations_by_type),
                total_searches=self._total_searches,
                average_search_time_ms=(
                    self._search_time_total_ms / self._total_searches
                    if self._total_searches > 0 else 0.0
                ),
                search_result_avg=(
                    self._search_results_total / self._total_searches
                    if self._total_searches > 0 else 0.0
                ),
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                cache_hit_ratio=(
                    self._cache_hits / (self._cache_hits + self._cache_misses)
                    if (self._cache_hits + self._cache_misses) > 0 else 0.0
                ),
                total_archived_by_cleaner=self._total_archived,
                total_deleted_by_cleaner=self._total_deleted,
                total_compressed=self._total_compressed,
                last_cleanup_time=self._last_cleanup_time,
                uptime_hours=uptime,
                start_time=self._start_time,
            )

            # Average latency
            if self._total_operations > 0:
                snapshot.average_latency_ms = self._latency_total_ms / self._total_operations

            # Per-operation latency
            for op, latencies in self._latency_by_operation.items():
                if latencies:
                    snapshot.latency_by_operation[op] = sum(latencies) / len(latencies)

        # Fetch live data if store provided
        if memory_store:
            try:
                snapshot.total_memories = memory_store.count()
                snapshot.cache_size = memory_store.cache.size

                # Count by type
                for mem_type in [
                    "CONVERSATION", "PREFERENCE", "PROJECT", "CONTACT",
                    "CODE", "TASK", "SYSTEM", "TEMPORARY", "KNOWLEDGE",
                ]:
                    count = memory_store.count(memory_type=mem_type)
                    if count > 0:
                        snapshot.total_by_type[mem_type] = count

            except Exception as e:
                logger.warning(f"Failed to fetch live metrics: {e}")

        return snapshot

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def report(self, memory_store=None) -> str:
        """Generate a human-readable metrics report.

        Args:
            memory_store: optional MemoryStore for live data

        Returns:
            formatted string report
        """
        snap = self.snapshot(memory_store)

        lines = [
            "=" * 50,
            "MEMORY SYSTEM METRICS",
            "=" * 50,
            "",
            f"Uptime: {snap.uptime_hours:.1f} hours",
            "",
            "--- General ---",
            f"Total Memories: {snap.total_memories}",
            f"Archived: {snap.total_archived}",
            f"Pinned: {snap.total_pinned}",
            f"By Type:",
        ]

        for mem_type, count in sorted(snap.total_by_type.items()):
            lines.append(f"  {mem_type.lower()}: {count}")

        lines.extend([
            "",
            "--- Operations ---",
            f"Total: {snap.total_operations}",
            f"By Type: {snap.operations_by_type}",
            f"Avg Latency: {snap.average_latency_ms:.1f}ms",
            f"By Operation: {snap.latency_by_operation}",
            "",
            "--- Search ---",
            f"Total Searches: {snap.total_searches}",
            f"Avg Time: {snap.average_search_time_ms:.1f}ms",
            f"Avg Results: {snap.search_result_avg:.1f}",
            "",
            "--- Cache ---",
            f"Size: {snap.cache_size}",
            f"Hits: {snap.cache_hits}",
            f"Misses: {snap.cache_misses}",
            f"Hit Ratio: {snap.cache_hit_ratio:.1%}",
            "",
            "--- Cleanup ---",
            f"Last Cleanup: {snap.last_cleanup_time}",
            f"Total Archived: {snap.total_archived_by_cleaner}",
            f"Total Deleted: {snap.total_deleted_by_cleaner}",
            f"Total Compressed: {snap.total_compressed}",
        ])

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._total_operations = 0
            self._operations_by_type.clear()
            self._latency_total_ms = 0.0
            self._latency_by_operation.clear()
            self._total_searches = 0
            self._search_time_total_ms = 0.0
            self._search_results_total = 0
            self._cache_hits = 0
            self._cache_misses = 0
            self._last_cleanup_time = 0.0
            self._total_archived = 0
            self._total_deleted = 0
            self._total_compressed = 0
            self._start_time = time.time()
            logger.info("Memory metrics reset")

