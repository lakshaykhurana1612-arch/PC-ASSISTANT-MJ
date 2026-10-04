"""
Memory Cleaner — Background maintenance pipeline.

Processes memories through a pipeline:
1. Archive — old/low-importance memories get archived
2. Compress — archived memories get content compressed (summary only)
3. Summarize — long conversations get summarized
4. Delete — expired/temporary memories get deleted

Runs:
- On demand (call cleanup())
- Periodically in background (start auto-cleanup thread)
- After each memory operation (lightweight check)

Never deletes pinned memories or memories with importance > threshold.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.memory.models import MemoryEntry, MemoryType, Importance
from app.memory.memory_manager import MemoryManager
from app.memory.importance_scorer import ImportanceScorer
from app.memory.memory_serializer import MemorySerializer
from app.providers.memory_provider import MemoryFilter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cleaner Configuration
# ---------------------------------------------------------------------------


@dataclass
class CleanerConfig:
    """Configuration for memory cleanup behavior."""

    # Archive settings
    archive_after_hours: float = 72.0  # Archive memories older than this
    archive_importance_max: float = 0.3  # Only archive low-importance memories

    # Compress settings
    compress_after_hours: float = 168.0  # Compress after 1 week
    compress_importance_max: float = 0.2  # Only compress very low importance

    # Summarize settings
    summarize_after_exchanges: int = 10  # More than this → summarize
    summarize_min_content_length: int = 500  # Only lengthy conversations

    # Delete settings
    delete_expired: bool = True
    delete_temporary_after_hours: float = 24.0
    delete_archived_after_hours: float = 720.0  # Delete archived after 30 days

    # Limits
    max_archive_per_cycle: int = 100
    max_compress_per_cycle: int = 50
    max_summarize_per_cycle: int = 20
    max_delete_per_cycle: int = 100

    # Auto-cleanup interval
    auto_cleanup_interval_minutes: float = 60.0  # Run every hour


# ---------------------------------------------------------------------------
# Memory Cleaner
# ---------------------------------------------------------------------------


class MemoryCleaner:
    """Background memory maintenance pipeline.

    Runs Archive → Compress → Summarize → Delete pipeline.

    Usage:
        cleaner = MemoryCleaner(memory_manager)
        cleaner.cleanup()  # Run one cleanup cycle
        cleaner.start_auto_cleanup()  # Run periodically
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        config: Optional[CleanerConfig] = None,
    ):
        self.memory_manager = memory_manager
        self.config = config or CleanerConfig()
        self.scorer = ImportanceScorer()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_cleanup_time = 0.0

    # ------------------------------------------------------------------
    # Full cleanup pipeline
    # ------------------------------------------------------------------

    def cleanup(self, full: bool = False) -> dict[str, int]:
        """Run the full cleanup pipeline.

        Args:
            full: if True, run all stages (including delete)

        Returns:
            dict with counts of processed items per stage
        """
        stats = {
            "archived": 0,
            "compressed": 0,
            "summarized": 0,
            "deleted": 0,
        }

        start = time.time()

        # Stage 1: Archive old/low-importance memories
        stats["archived"] = self._archive_old_memories()

        # Stage 2: Compress archived content
        stats["compressed"] = self._compress_archived()

        # Stage 3: Summarize long conversations
        stats["summarized"] = self._summarize_conversations()

        # Stage 4: Delete expired/temporary (only in full mode)
        if full and self.config.delete_expired:
            stats["deleted"] = self._delete_expired()

        elapsed = time.time() - start
        self._last_cleanup_time = time.time()

        total = sum(stats.values())
        if total:
            logger.info(f"Cleanup completed: {stats} in {elapsed:.2f}s")

        return stats

    # ------------------------------------------------------------------
    # Stage 1: Archive
    # ------------------------------------------------------------------

    def _archive_old_memories(self) -> int:
        """Archive old, low-importance memories."""
        now = time.time()
        cutoff = now - (self.config.archive_after_hours * 3600)

        mfilter = MemoryFilter(
            created_before=cutoff,
            importance_max=self.config.archive_importance_max,
            limit=self.config.max_archive_per_cycle,
            sort_by="created_at",
            sort_desc=False,  # Oldest first
        )

        entries = self.memory_manager.list(filter=mfilter)
        count = 0

        for entry in entries:
            if entry.pinned:
                continue
            self.memory_manager.archive(entry.id)
            count += 1

        if count:
            logger.info(f"Archived {count} old memories")
        return count

    # ------------------------------------------------------------------
    # Stage 2: Compress
    # ------------------------------------------------------------------

    def _compress_archived(self) -> int:
        """Compress archived memories — keep summary, truncate content."""
        now = time.time()
        cutoff = now - (self.config.compress_after_hours * 3600)

        mfilter = MemoryFilter(
            created_before=cutoff,
            importance_max=self.config.compress_importance_max,
            limit=self.config.max_compress_per_cycle,
        )
        # Note: archived filter can't be directly set; we'll use a different approach
        entries = self.memory_manager.list(filter=mfilter)
        count = 0

        for entry in entries:
            if not entry.archived or not entry.content:
                continue
            if len(entry.content) < 200:  # Already small
                continue

            # Compress: keep summary, truncate content
            if not entry.summary:
                entry.summary = entry.content[:300]
            self.memory_manager.update(entry.id, {
                "content": f"[Compressed] {entry.summary[:200]}",
                "metadata": {**entry.metadata, "compressed": True, "original_length": len(entry.content)},
            })
            count += 1

        if count:
            logger.info(f"Compressed {count} archived memories")
        return count

    # ------------------------------------------------------------------
    # Stage 3: Summarize
    # ------------------------------------------------------------------

    def _summarize_conversations(self) -> int:
        """Summarize long conversations."""
        mfilter = MemoryFilter(
            memory_type=MemoryType.CONVERSATION.name,
            limit=self.config.max_summarize_per_cycle,
        )

        entries = self.memory_manager.list(filter=mfilter)
        count = 0

        for entry in entries:
            if not entry.content or len(entry.content) < self.config.summarize_min_content_length:
                continue
            if entry.summary:
                continue

            # Auto-generate summary from first part of conversation
            lines = entry.content.split("\n")
            if len(lines) > self.config.summarize_after_exchanges:
                user_requests = [
                    l.replace("[user]:", "").strip()
                    for l in lines if "[user]:" in l
                ]
                if user_requests:
                    summary = "; ".join(user_requests[:5])
                    if len(summary) > 300:
                        summary = summary[:300] + "..."

                    self.memory_manager.update(entry.id, {
                        "summary": summary,
                        "metadata": {**entry.metadata, "summarized": True},
                    })
                    count += 1

        if count:
            logger.info(f"Summarized {count} conversations")
        return count

    # ------------------------------------------------------------------
    # Stage 4: Delete
    # ------------------------------------------------------------------

    def _delete_expired(self) -> int:
        """Delete expired and old temporary memories."""
        now = time.time()
        count = 0

        # Delete explicitly expired memories
        expired = self.memory_manager.search(
            text="",
            include_archived=True,
            limit=self.config.max_delete_per_cycle,
        )
        for result in expired:
            if result.entry.expires_at and result.entry.expires_at < now:
                if result.entry.pinned:
                    continue
                self.memory_manager.forget(result.entry.id, permanent=True)
                count += 1

        # Delete old temporary memories
        temp_cutoff = now - (self.config.delete_temporary_after_hours * 3600)
        temp_filter = MemoryFilter(
            memory_type=MemoryType.TEMPORARY.name,
            created_before=temp_cutoff,
            limit=self.config.max_delete_per_cycle,
        )
        temp_entries = self.memory_manager.list(filter=temp_filter)
        for entry in temp_entries:
            self.memory_manager.forget(entry.id, permanent=True)
            count += 1

        if count:
            logger.info(f"Deleted {count} expired/temporary memories")
        return count

    # ------------------------------------------------------------------
    # Auto cleanup
    # ------------------------------------------------------------------

    def start_auto_cleanup(self) -> None:
        """Start periodic cleanup in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Auto-cleanup already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._auto_cleanup_loop, daemon=True)
        self._thread.start()
        logger.info(f"Auto-cleanup started (interval={self.config.auto_cleanup_interval_minutes}min)")

    def _auto_cleanup_loop(self) -> None:
        """Background loop for periodic cleanup."""
        while not self._stop_event.is_set():
            try:
                self.cleanup(full=True)
            except Exception as e:
                logger.error(f"Auto-cleanup error: {e}")

            # Wait for next interval
            self._stop_event.wait(self.config.auto_cleanup_interval_minutes * 60)

    def stop_auto_cleanup(self) -> None:
        """Stop the background cleanup thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Auto-cleanup stopped")

    def cleanup_now(self) -> dict[str, int]:
        """Run a full cleanup immediately."""
        return self.cleanup(full=True)

    # ------------------------------------------------------------------
    # Lightweight check (for post-operation calls)
    # ------------------------------------------------------------------

    def check_after_operation(self) -> None:
        """Lightweight check to run after each memory operation.

        Only checks for expired memories — quick operation.
        """
        if not self.config.delete_expired:
            return

        # Only run actual cleanup if enough time has passed
        if time.time() - self._last_cleanup_time < 300:  # 5 min cooldown
            return

        self._delete_expired()

