"""
SQLite Memory Provider — Persistent storage for memories.

Uses only 4 tables:
1. memories — main storage (all fields in a single table)
2. embeddings — vector embeddings (separated for performance)
3. sessions — session state
4. preferences — user preferences

All memory types (conversation, project, contact, etc.) share the 'memories' table.
Difference is only in the 'memory_type' column.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from app.providers.memory_provider import (
    MemoryProvider,
    MemoryProviderError,
    MemoryNotFoundError,
    MemoryDuplicateError,
    MemoryFilter,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

# Default database path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "mj_memory.db",
)


# ---------------------------------------------------------------------------
# SQLite Provider
# ---------------------------------------------------------------------------


class SQLiteMemoryProvider(MemoryProvider):
    """SQLite-based memory storage provider.

    All memory types stored in a single 'memories' table.
    Embeddings stored separately in 'embeddings' table for performance.

    Usage:
        provider = SQLiteMemoryProvider("path/to/memory.db")
        provider.initialize()
        provider.create(entry_dict)
        results = provider.search("query text")
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def _connection(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            conn = self._connection

            # Schema version tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                )
            """)

            # ===== MEMORIES TABLE (unified) =====
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL DEFAULT 'CONVERSATION',
                    source TEXT NOT NULL DEFAULT 'MJ',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    importance REAL NOT NULL DEFAULT 0.5,
                    importance_factors TEXT NOT NULL DEFAULT '{}',
                    tags TEXT NOT NULL DEFAULT '[]',
                    keywords TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    accessed_at REAL NOT NULL DEFAULT 0,
                    expires_at REAL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    update_count INTEGER NOT NULL DEFAULT 0,
                    reference_count INTEGER NOT NULL DEFAULT 0,
                    parent_id TEXT,
                    related_ids TEXT NOT NULL DEFAULT '[]'
                )
            """)

            # ===== EMBEDDINGS TABLE (separated for performance) =====
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    memory_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    dimension INTEGER NOT NULL DEFAULT 384,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)

            # ===== SESSIONS TABLE =====
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    session_type TEXT NOT NULL DEFAULT 'USER',
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL
                )
            """)

            # ===== PREFERENCES TABLE =====
            conn.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    updated_at REAL NOT NULL
                )
            """)

            # ===== INDEXES =====
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(pinned)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_archived ON memories(archived)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_parent ON memories(parent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type)")

            conn.commit()
            logger.info(f"SQLite memory initialized at: {self.db_path}")

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def create(self, entry: dict) -> str:
        """Store a new memory entry."""
        memory_id = entry.get("id", "")
        if not memory_id:
            import uuid
            memory_id = uuid.uuid4().hex[:24]

        now = time.time()

        with self._lock:
            conn = self._connection

            # Check for duplicate
            if memory_id:
                existing = conn.execute(
                    "SELECT id FROM memories WHERE id = ?", (memory_id,)
                ).fetchone()
                if existing:
                    raise MemoryDuplicateError(f"Memory '{memory_id}' already exists")

            conn.execute("""
                INSERT INTO memories (
                    id, memory_type, source, title, content, summary,
                    metadata, importance, importance_factors,
                    tags, keywords,
                    created_at, updated_at, accessed_at,
                    expires_at, pinned, archived, deleted,
                    access_count, update_count, reference_count,
                    parent_id, related_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory_id,
                entry.get("memory_type", "CONVERSATION"),
                entry.get("source", "MJ"),
                entry.get("title", ""),
                entry.get("content", ""),
                entry.get("summary", ""),
                json.dumps(entry.get("metadata", {})),
                float(entry.get("importance", 0.5)),
                json.dumps(entry.get("importance_factors", {})),
                json.dumps(entry.get("tags", [])),
                json.dumps(entry.get("keywords", [])),
                entry.get("created_at", now),
                entry.get("updated_at", now),
                entry.get("accessed_at", now),
                entry.get("expires_at"),
                1 if entry.get("pinned") else 0,
                1 if entry.get("archived") else 0,
                1 if entry.get("deleted") else 0,
                entry.get("access_count", 0),
                entry.get("update_count", 0),
                entry.get("reference_count", 0),
                entry.get("parent_id"),
                json.dumps(entry.get("related_ids", [])),
            ))

            conn.commit()

        return memory_id

    def read(self, memory_id: str) -> Optional[dict]:
        """Retrieve a memory by ID."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()

        if row is None:
            return None

        entry = self._row_to_dict(row)

        # Update access count
        self._update_access_count(memory_id)

        return entry

    def update(self, memory_id: str, data: dict) -> bool:
        """Update an existing memory."""
        with self._lock:
            conn = self._connection

            # Check exists
            existing = conn.execute(
                "SELECT id FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not existing:
                return False

            # Build update fields
            fields = []
            values = []

            updatable = [
                "memory_type", "source", "title", "content", "summary",
                "importance", "pinned", "archived", "deleted",
                "parent_id",
            ]
            json_fields = ["metadata", "importance_factors", "tags", "keywords", "related_ids"]

            for key in updatable:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])

            for key in json_fields:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(json.dumps(data[key]))

            if not fields:
                return True  # Nothing to update

            # Always update timestamp
            fields.append("updated_at = ?")
            values.append(time.time())

            # Increment update count
            fields.append("update_count = update_count + 1")

            values.append(memory_id)

            conn.execute(
                f"UPDATE memories SET {', '.join(fields)} WHERE id = ?",
                values
            )
            conn.commit()

        return True

    def delete(self, memory_id: str, permanent: bool = False) -> bool:
        """Delete a memory."""
        with self._lock:
            conn = self._connection

            if permanent:
                cursor = conn.execute(
                    "DELETE FROM memories WHERE id = ?", (memory_id,)
                )
            else:
                cursor = conn.execute(
                    "UPDATE memories SET deleted = 1, archived = 1, updated_at = ? WHERE id = ?",
                    (time.time(), memory_id)
                )

            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Search & List
    # ------------------------------------------------------------------

    def search(self, query: str, filter: Optional[MemoryFilter] = None) -> list[dict]:
        """Search memories by keyword matching on title, content, summary, tags.

        For semantic search, use VectorStore. This provides basic keyword search.
        """
        if not query or not query.strip():
            return self.list(filter or MemoryFilter())

        with self._lock:
            sql = "SELECT * FROM memories WHERE deleted = 0"
            params = []

            # Text search across multiple fields
            search_terms = query.strip().lower().split()
            for term in search_terms:
                like = f"%{term}%"
                sql += """ AND (
                    LOWER(title) LIKE ? OR
                    LOWER(content) LIKE ? OR
                    LOWER(summary) LIKE ? OR
                    LOWER(tags) LIKE ?
                )"""
                params.extend([like, like, like, like])

            # Apply filter
            sql, filter_params = self._apply_filter(filter)
            params.extend(filter_params)

            sql += " ORDER BY importance DESC, created_at DESC"

            if filter and filter.limit:
                sql += f" LIMIT {filter.limit}"
            if filter and filter.offset:
                sql += f" OFFSET {filter.offset}"

            rows = self._connection.execute(sql, params).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def list(self, filter: MemoryFilter) -> list[dict]:
        """List memories with optional filtering."""
        with self._lock:
            sql = "SELECT * FROM memories WHERE deleted = 0"
            params = []

            sql, filter_params = self._apply_filter(filter)
            params.extend(filter_params)

            # Sort
            sort_col = "created_at"
            if filter.sort_by == "importance":
                sort_col = "importance"
            elif filter.sort_by == "last_accessed":
                sort_col = "accessed_at"

            sort_dir = "DESC" if filter.sort_desc else "ASC"
            sql += f" ORDER BY {sort_col} {sort_dir}"

            if filter.limit:
                sql += f" LIMIT {filter.limit}"
            if filter.offset:
                sql += f" OFFSET {filter.offset}"

            rows = self._connection.execute(sql, params).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def count(self, filter: MemoryFilter) -> int:
        """Count memories matching filter."""
        with self._lock:
            sql = "SELECT COUNT(*) FROM memories WHERE deleted = 0"
            params = []

            sql, filter_params = self._apply_filter(filter)
            params.extend(filter_params)

            result = self._connection.execute(sql, params).fetchone()

        return result[0] if result else 0

    def _apply_filter(self, filter: Optional[MemoryFilter]) -> tuple[str, list]:
        """Build SQL WHERE clause from MemoryFilter."""
        if filter is None:
            return "", []

        sql = ""
        params = []

        if filter.memory_type:
            sql += " AND memory_type = ?"
            params.append(filter.memory_type)

        if filter.importance_min > 0:
            sql += " AND importance >= ?"
            params.append(filter.importance_min)

        if filter.importance_max < 1.0:
            sql += " AND importance <= ?"
            params.append(filter.importance_max)

        if filter.tags:
            for tag in filter.tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        if filter.created_after:
            sql += " AND created_at >= ?"
            params.append(filter.created_after)

        if filter.created_before:
            sql += " AND created_at <= ?"
            params.append(filter.created_before)

        if filter.source:
            sql += " AND source = ?"
            params.append(filter.source)

        if filter.pinned_only:
            sql += " AND pinned = 1"

        if not filter.archived:
            sql += " AND archived = 0"

        return sql, params

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def set_preference(self, key: str, value: Any, category: str = "general") -> None:
        """Set a user preference."""
        with self._lock:
            self._connection.execute("""
                INSERT INTO preferences (key, value, category, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
            """, (key, json.dumps(value) if not isinstance(value, str) else value, category, time.time()))
            self._connection.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        row = self._connection.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def get_all_preferences(self, category: Optional[str] = None) -> dict:
        """Get all preferences, optionally filtered by category."""
        if category:
            rows = self._connection.execute(
                "SELECT key, value FROM preferences WHERE category = ?", (category,)
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT key, value FROM preferences"
            ).fetchall()

        result = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                result[row["key"]] = row["value"]
        return result

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def bulk_create(self, entries: list[dict]) -> list[str]:
        """Store multiple memories in a single transaction."""
        ids = []
        with self._lock:
            conn = self._connection
            for entry in entries:
                mid = entry.get("id", "")
                if not mid:
                    import uuid
                    mid = uuid.uuid4().hex[:24]
                    entry["id"] = mid
                ids.append(mid)

            # Use executemany for performance
            data = []
            now = time.time()
            for e in entries:
                data.append((
                    e.get("id"), e.get("memory_type", "CONVERSATION"),
                    e.get("source", "MJ"), e.get("title", ""),
                    e.get("content", ""), e.get("summary", ""),
                    json.dumps(e.get("metadata", {})),
                    float(e.get("importance", 0.5)),
                    json.dumps(e.get("importance_factors", {})),
                    json.dumps(e.get("tags", [])),
                    json.dumps(e.get("keywords", [])),
                    e.get("created_at", now), e.get("updated_at", now),
                    e.get("accessed_at", now), e.get("expires_at"),
                    1 if e.get("pinned") else 0,
                    1 if e.get("archived") else 0,
                    1 if e.get("deleted") else 0,
                    e.get("access_count", 0), e.get("update_count", 0),
                    e.get("reference_count", 0), e.get("parent_id"),
                    json.dumps(e.get("related_ids", [])),
                ))

            conn.executemany("""
                INSERT INTO memories (
                    id, memory_type, source, title, content, summary,
                    metadata, importance, importance_factors,
                    tags, keywords,
                    created_at, updated_at, accessed_at,
                    expires_at, pinned, archived, deleted,
                    access_count, update_count, reference_count,
                    parent_id, related_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            conn.commit()

        return ids

    def clear(self) -> None:
        """Clear all memories (use with caution)."""
        with self._lock:
            self._connection.execute("DELETE FROM memories")
            self._connection.execute("DELETE FROM embeddings")
            self._connection.commit()
            logger.warning("All memories cleared from SQLite store.")

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        """Vacuum the database to reclaim space."""
        with self._lock:
            self._connection.execute("VACUUM")
            logger.info("SQLite database vacuumed.")

    def cleanup_expired(self) -> int:
        """Remove expired memories. Returns count removed."""
        with self._lock:
            now = time.time()
            cursor = self._connection.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,)
            )
            self._connection.commit()
        count = cursor.rowcount
        if count:
            logger.info(f"Cleaned up {count} expired memories.")
        return count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                logger.info("SQLite connection closed.")

    def health_check(self) -> dict:
        """Check if the database is healthy."""
        try:
            with self._lock:
                result = self._connection.execute("SELECT COUNT(*) as count FROM memories").fetchone()
                count = result["count"] if result else 0
            return {
                "status": "ok",
                "details": {
                    "total_memories": count,
                    "db_path": self.db_path,
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "details": {"error": str(e)},
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_access_count(self, memory_id: str) -> None:
        """Increment access count and update accessed_at timestamp."""
        try:
            self._connection.execute(
                "UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                (time.time(), memory_id)
            )
            self._connection.commit()
        except Exception:
            pass  # Non-critical

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a dict with parsed JSON fields."""
        d = dict(row)
        # Parse JSON fields
        for json_field in ["metadata", "importance_factors", "tags", "keywords", "related_ids"]:
            if json_field in d and isinstance(d[json_field], str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    d[json_field] = {} if json_field in ("metadata", "importance_factors") else []
        # Convert integers to bools
        for bool_field in ["pinned", "archived", "deleted"]:
            if bool_field in d:
                d[bool_field] = bool(d[bool_field])
        return d

