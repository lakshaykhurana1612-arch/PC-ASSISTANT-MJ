"""
MJ Memory System — Unified memory with hybrid search and provider-based backends.

Architecture:
    MemoryManager (single public API)
        → MemoryStore (coordinates SQLite + FAISS + Cache)
            → MemoryProvider (SQLite — persistent storage)
            → EmbeddingProvider (SentenceTransformer — vector embeddings)
            → VectorProvider (FAISS — vector similarity search)
        → MemoryObserver (auto-saves from pipeline events)
        → MemoryCleaner (archive → compress → summarize → delete)

Public API (use ONLY MemoryManager):
    remember()  — Store a new memory
    recall()    — Retrieve by ID
    search()    — Hybrid search (semantic + keyword + importance + recency)
    update()    — Update existing memory
    forget()    — Delete/archive
    pin()       — Prevent auto-delete
    archive()   — Soft-delete
    summarize() — Generate summary
    cleanup()   — Run maintenance
    merge()     — Merge memories

All memory types use the same MemoryEntry schema with metadata differentiation.
"""

from app.memory.models import (
    MemoryEntry,
    MemoryQuery,
    MemoryResult,
    MemoryType,
    MemorySource,
    Importance,
)
from app.memory.memory_manager import (
    MemoryManager,
    MemoryManagerConfig,
)
from app.memory.memory_serializer import MemorySerializer
from app.memory.importance_scorer import ImportanceScorer, ImportanceFactors

__all__ = [
    # Core models
    "MemoryEntry",
    "MemoryQuery",
    "MemoryResult",
    "MemoryType",
    "MemorySource",
    "Importance",

    # Manager (main API)
    "MemoryManager",
    "MemoryManagerConfig",

    # Utilities
    "MemorySerializer",
    "ImportanceScorer",
    "ImportanceFactors",
]

