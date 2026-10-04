"""
Memory Serializer — Serialize/deserialize memory entries.

Handles conversion between:
- MemoryEntry <-> dict (for storage/API)
- MemoryEntry <-> JSON (for export/import)
- MemoryEntry <-> text summary (for LLM prompts)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.memory.models import MemoryEntry, MemoryType, MemorySource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


class MemorySerializer:
    """Serialize and deserialize memory entries.

    Usage:
        serializer = MemorySerializer()

        # To dict for storage
        d = serializer.to_dict(entry)

        # From dict from storage
        entry = serializer.from_dict(d)

        # To JSON string for export
        json_str = serializer.to_json(entry)

        # To text summary for LLM prompts
        text = serializer.summarize_for_llm(entry)
    """

    # ------------------------------------------------------------------
    # Dict conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_dict(entry: MemoryEntry) -> dict[str, Any]:
        """Convert MemoryEntry to a plain dict for storage.

        Handles enum serialization.
        """
        result = {}
        for k, v in entry.__dict__.items():
            # Handle enums
            if isinstance(v, MemoryType):
                result[k] = v.name
            elif isinstance(v, MemorySource):
                result[k] = v.name
            elif isinstance(v, Enum):
                result[k] = v.name if hasattr(v, 'name') else str(v)
            else:
                result[k] = v
        return result

    @staticmethod
    def from_dict(data: dict) -> MemoryEntry:
        """Create MemoryEntry from a plain dict.

        Handles enum deserialization.
        """
        # Convert string enums back to enum values
        if "memory_type" in data and isinstance(data["memory_type"], str):
            try:
                data["memory_type"] = MemoryType[data["memory_type"]]
            except KeyError:
                data["memory_type"] = MemoryType.CONVERSATION

        if "source" in data and isinstance(data["source"], str):
            try:
                data["source"] = MemorySource[data["source"]]
            except KeyError:
                data["source"] = MemorySource.MJ

        # Filter to only valid fields
        valid_fields = set(MemoryEntry.__dataclass_fields__.keys())
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        return MemoryEntry(**filtered)

    # ------------------------------------------------------------------
    # JSON conversion
    # ------------------------------------------------------------------

    @staticmethod
    def to_json(entry: MemoryEntry, indent: int = 2) -> str:
        """Serialize MemoryEntry to JSON string."""
        d = MemorySerializer.to_dict(entry)

        # Convert timestamp floats to ISO format for readability
        for ts_field in ["created_at", "updated_at", "accessed_at", "expires_at"]:
            if ts_field in d and isinstance(d[ts_field], (int, float)) and d[ts_field] > 0:
                try:
                    d[ts_field] = datetime.fromtimestamp(d[ts_field]).isoformat()
                except (OSError, ValueError):
                    pass

        return json.dumps(d, indent=indent, ensure_ascii=False, default=str)

    @staticmethod
    def from_json(json_str: str) -> MemoryEntry:
        """Deserialize MemoryEntry from JSON string."""
        data = json.loads(json_str)

        # Convert ISO format timestamps back to floats
        for ts_field in ["created_at", "updated_at", "accessed_at", "expires_at"]:
            if ts_field in data and isinstance(data[ts_field], str):
                try:
                    data[ts_field] = datetime.fromisoformat(data[ts_field]).timestamp()
                except (ValueError, TypeError):
                    pass

        return MemorySerializer.from_dict(data)

    # ------------------------------------------------------------------
    # Batch conversion
    # ------------------------------------------------------------------

    @staticmethod
    def batch_to_dict(entries: list[MemoryEntry]) -> list[dict]:
        """Convert multiple entries to dicts."""
        return [MemorySerializer.to_dict(e) for e in entries]

    @staticmethod
    def batch_from_dict(data_list: list[dict]) -> list[MemoryEntry]:
        """Create multiple entries from dicts."""
        return [MemorySerializer.from_dict(d) for d in data_list]

    @staticmethod
    def batch_to_json(entries: list[MemoryEntry], indent: int = 2) -> str:
        """Serialize multiple entries to JSON array."""
        dicts = MemorySerializer.batch_to_dict(entries)
        return json.dumps(dicts, indent=indent, ensure_ascii=False, default=str)

    @staticmethod
    def batch_from_json(json_str: str) -> list[MemoryEntry]:
        """Deserialize JSON array to entries."""
        data_list = json.loads(json_str)
        return MemorySerializer.batch_from_dict(data_list)

    # ------------------------------------------------------------------
    # LLM prompt formatting
    # ------------------------------------------------------------------

    @staticmethod
    def summarize_for_llm(entry: MemoryEntry, max_length: int = 500) -> str:
        """Format a memory entry as text for LLM context injection.

        Creates a concise, readable summary.

        Args:
            entry: MemoryEntry to format
            max_length: maximum output length

        Returns:
            formatted text summary
        """
        parts = []

        # Type badge
        mem_type = entry.memory_type
        if isinstance(mem_type, MemoryType):
            mem_type = mem_type.name
        parts.append(f"[{mem_type}]")

        # Title
        if entry.title:
            parts.append(entry.title)

        # Summary or truncated content
        if entry.summary:
            parts.append(f"- {entry.summary[:max_length]}")
        elif entry.content:
            content = entry.content[:max_length]
            if len(entry.content) > max_length:
                content += "..."
            parts.append(f"- {content}")

        # Tags
        if entry.tags:
            tags_str = ", ".join(entry.tags[:5])
            parts.append(f"[Tags: {tags_str}]")

        # Importance
        importance_label = "high" if entry.importance >= 0.7 else "medium" if entry.importance >= 0.4 else "low"
        parts.append(f"({importance_label} importance)")

        return " ".join(parts)

    @staticmethod
    def batch_summarize_for_llm(entries: list[MemoryEntry], max_entries: int = 5) -> str:
        """Format multiple memories as a single prompt block.

        Args:
            entries: list of MemoryEntry
            max_entries: max number to include

        Returns:
            formatted block for LLM prompt
        """
        if not entries:
            return "[No relevant memories found]"

        lines = ["[Relevant Memories]"]
        for i, entry in enumerate(entries[:max_entries]):
            summary = MemorySerializer.summarize_for_llm(entry, max_length=300)
            lines.append(f"{i+1}. {summary}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Export/Import
    # ------------------------------------------------------------------

    @staticmethod
    def export_to_file(entries: list[MemoryEntry], filepath: str, format: str = "json") -> None:
        """Export memories to a file.

        Args:
            entries: list of MemoryEntry to export
            filepath: output file path
            format: 'json' or 'jsonl'
        """
        if format == "jsonl":
            with open(filepath, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(MemorySerializer.to_json(entry, indent=None) + "\n")
        else:
            json_str = MemorySerializer.batch_to_json(entries)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_str)

        logger.info(f"Exported {len(entries)} memories to {filepath}")

    @staticmethod
    def import_from_file(filepath: str, format: str = "json") -> list[MemoryEntry]:
        """Import memories from a file.

        Args:
            filepath: input file path
            format: 'json' or 'jsonl'

        Returns:
            list of MemoryEntry
        """
        entries = []
        if format == "jsonl":
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(MemorySerializer.from_json(line))
        else:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                entries = MemorySerializer.batch_from_json(content)

        logger.info(f"Imported {len(entries)} memories from {filepath}")
        return entries


from enum import Enum  # Import needed for isinstance checks

