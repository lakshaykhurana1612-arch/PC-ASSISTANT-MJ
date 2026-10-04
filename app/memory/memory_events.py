"""
Memory Events — Event types for memory lifecycle.

Emit events on:
- Memory created
- Memory updated
- Memory deleted
- Memory archived
- Memory restored
- Memory accessed
- Memory search
- Memory importance changed
- Memory cleanup
- Memory error

These events integrate with the existing EventBus in app/events/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.events.events import MJEvent, EventCategory


# ---------------------------------------------------------------------------
# Memory Events
# ---------------------------------------------------------------------------


@dataclass
class MemoryCreatedEvent(MJEvent):
    """Emitted when a new memory is created."""

    memory_id: str = ""
    memory_type: str = ""
    importance: float = 0.0
    source: str = ""
    title: str = ""
    has_embedding: bool = False

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.created",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryUpdatedEvent(MJEvent):
    """Emitted when a memory is updated."""

    memory_id: str = ""
    memory_type: str = ""
    fields_updated: list[str] = field(default_factory=list)

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.updated",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryDeletedEvent(MJEvent):
    """Emitted when a memory is deleted."""

    memory_id: str = ""
    memory_type: str = ""
    permanent: bool = False

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.deleted",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryArchivedEvent(MJEvent):
    """Emitted when a memory is archived."""

    memory_id: str = ""
    memory_type: str = ""

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.archived",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryRestoredEvent(MJEvent):
    """Emitted when a memory is restored from archive."""

    memory_id: str = ""
    memory_type: str = ""

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.restored",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryAccessedEvent(MJEvent):
    """Emitted when a memory is accessed/retrieved."""

    memory_id: str = ""
    access_type: str = ""  # read, search_result, referenced

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.accessed",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemorySearchEvent(MJEvent):
    """Emitted when a memory search is performed."""

    query: str = ""
    result_count: int = 0
    search_time_ms: float = 0.0
    strategies_used: list[str] = field(default_factory=list)

    def __init__(self, **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.search",
            **kwargs,
        )


@dataclass
class MemoryImportanceEvent(MJEvent):
    """Emitted when a memory's importance changes."""

    memory_id: str = ""
    old_importance: float = 0.0
    new_importance: float = 0.0
    reason: str = ""

    def __init__(self, memory_id: str = "", **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.importance_changed",
            **kwargs,
        )
        self.memory_id = memory_id


@dataclass
class MemoryCleanupEvent(MJEvent):
    """Emitted during memory cleanup operations."""

    action: str = ""  # archive, compress, summarize, delete
    count: int = 0
    details: Optional[dict] = None

    def __init__(self, **kwargs):
        super().__init__(
            category=EventCategory.SYSTEM,
            name="memory.cleanup",
            **kwargs,
        )


@dataclass
class MemoryErrorEvent(MJEvent):
    """Emitted on memory system errors."""

    operation: str = ""  # create, read, update, delete, search
    error_message: str = ""
    memory_id: Optional[str] = None

    def __init__(self, **kwargs):
        super().__init__(
            category=EventCategory.ERROR,
            name="memory.error",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Event name constants
# ---------------------------------------------------------------------------


class MemoryEventNames:
    """Constants for memory event names (for subscription)."""

    CREATED = "memory.created"
    UPDATED = "memory.updated"
    DELETED = "memory.deleted"
    ARCHIVED = "memory.archived"
    RESTORED = "memory.restored"
    ACCESSED = "memory.accessed"
    SEARCH = "memory.search"
    IMPORTANCE_CHANGED = "memory.importance_changed"
    CLEANUP = "memory.cleanup"
    ERROR = "memory.error"

    # Wildcard patterns for subscription
    ALL = "memory.*"
    ALL_CHANGES = "memory.created|memory.updated|memory.deleted"

