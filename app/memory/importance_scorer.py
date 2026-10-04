"""
Importance Scorer — Multi-factor memory importance scoring.

Scores memories based on multiple factors:
1. Recency — newer memories score higher
2. Frequency — frequently accessed memories score higher
3. Pinned — user-pinned memories get maximum score
4. Reference Count — memories referenced by other memories/agents
5. User Saved — explicitly saved by user
6. Developer Saved — saved by developer agent
7. Task Success — memories associated with successful task completion
8. Conversation Depth — deeper conversations count more
9. Keywords — memories matching common user keywords
10. Source — user-sourced > MI-sourced > system-sourced

Usage:
    scorer = ImportanceScorer()
    score = scorer.calculate(memory_entry)
    factors = scorer.get_factors(memory_entry)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.memory.models import MemoryEntry, Importance, MemorySource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factor definitions
# ---------------------------------------------------------------------------


@dataclass
class ImportanceFactors:
    """Breakdown of importance factors with individual scores."""

    recency: float = 0.0       # 0-1: How recent
    frequency: float = 0.0      # 0-1: How frequently accessed
    pinned: float = 0.0         # 0 or 1: Is pinned
    reference_count: float = 0.0  # 0-1: Times referenced
    user_saved: float = 0.0     # 0 or 1: User explicitly saved
    developer_saved: float = 0.0  # 0 or 1: Developer saved
    task_success: float = 0.0   # 0-1: Associated with success
    conversation_depth: float = 0.0  # 0-1: Depth of conversation
    keyword_relevance: float = 0.0  # 0-1: Keyword match with user patterns
    source_weight: float = 0.0   # 0-1: Source-based weight
    custom: float = 0.0          # Custom factor

    def total(self) -> float:
        """Weighted sum of all factors (0.0 to 1.0)."""
        weights = {
            "recency": 0.15,
            "frequency": 0.15,
            "pinned": 0.20,
            "reference_count": 0.10,
            "user_saved": 0.15,
            "developer_saved": 0.05,
            "task_success": 0.05,
            "conversation_depth": 0.05,
            "keyword_relevance": 0.05,
            "source_weight": 0.05,
        }
        total = 0.0
        for factor, weight in weights.items():
            total += getattr(self, factor, 0.0) * weight
        return min(total, 1.0)


# ---------------------------------------------------------------------------
# Importance Scorer
# ---------------------------------------------------------------------------


class ImportanceScorer:
    """Multi-factor memory importance scorer.

    Calculates importance (0.0 to 1.0) for any MemoryEntry.

    Usage:
        scorer = ImportanceScorer()
        score = scorer.calculate(entry)
        # 0.85
        factors = scorer.get_factors(entry)
        # ImportanceFactors(recency=0.9, frequency=0.5, pinned=1.0, ...)
    """

    # Half-life for recency decay (in hours)
    # After this many hours, recency factor drops to 0.5
    RECENCY_HALF_LIFE_HOURS = 24

    # How many accesses count as "frequent"
    FREQUENCY_THRESHOLD = 10

    # Source weights
    SOURCE_WEIGHTS = {
        MemorySource.USER.name: 1.0,
        MemorySource.MJ.name: 0.7,
        MemorySource.DEVELOPER.name: 0.8,
        MemorySource.SYSTEM.name: 0.4,
        MemorySource.IMPORT.name: 0.6,
        MemorySource.INFERRED.name: 0.3,
    }

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def calculate(self, entry: MemoryEntry) -> float:
        """Calculate overall importance for a memory entry.

        Args:
            entry: MemoryEntry to score

        Returns:
            float between 0.0 (trivial) and 1.0 (critical)
        """
        factors = self._compute_factors(entry)
        return factors.total()

    def get_factors(self, entry: MemoryEntry) -> ImportanceFactors:
        """Get detailed importance factor breakdown.

        Args:
            entry: MemoryEntry to score

        Returns:
            ImportanceFactors with individual factor scores
        """
        return self._compute_factors(entry)

    def batch_calculate(self, entries: list[MemoryEntry]) -> list[float]:
        """Calculate importance for multiple entries at once."""
        return [self.calculate(e) for e in entries]

    def _compute_factors(self, entry: MemoryEntry) -> ImportanceFactors:
        """Compute all importance factors for an entry."""
        now = time.time()

        factors = ImportanceFactors()

        # --- Recency ---
        age_hours = (now - entry.created_at) / 3600 if entry.created_at else 999
        factors.recency = self._compute_recency(age_hours)

        # --- Frequency ---
        factors.frequency = self._compute_frequency(entry.access_count)

        # --- Pinned ---
        factors.pinned = 1.0 if entry.pinned else 0.0

        # --- Reference Count ---
        factors.reference_count = self._compute_reference_count(entry.reference_count)

        # --- User Saved (from metadata) ---
        factors.user_saved = 1.0 if entry.metadata.get("user_saved", False) else 0.0

        # --- Developer Saved (from metadata) ---
        factors.developer_saved = 1.0 if entry.metadata.get("developer_saved", False) else 0.0

        # --- Task Success (from metadata) ---
        task_success = entry.metadata.get("task_success", None)
        factors.task_success = float(task_success) if task_success is not None else 0.5

        # --- Conversation Depth (from metadata) ---
        depth = entry.metadata.get("conversation_depth", 0)
        factors.conversation_depth = self._compute_conversation_depth(depth)

        # --- Keyword Relevance (from metadata) ---
        factors.keyword_relevance = entry.metadata.get("keyword_relevance", 0.5)

        # --- Source Weight ---
        factors.source_weight = self.SOURCE_WEIGHTS.get(entry.source, 0.5)

        return factors

    @staticmethod
    def _compute_recency(age_hours: float) -> float:
        """Compute recency score using exponential decay.

        Score = 2^(-age / half_life)
        """
        if age_hours <= 0:
            return 1.0
        half_life = ImportanceScorer.RECENCY_HALF_LIFE_HOURS
        return 2 ** (-age_hours / half_life)

    @staticmethod
    def _compute_frequency(access_count: int) -> float:
        """Compute frequency score using sigmoid.

        Score = sigmoid(access_count - threshold/2)
        """
        threshold = ImportanceScorer.FREQUENCY_THRESHOLD
        # Simple scaling
        return min(1.0, access_count / threshold)

    @staticmethod
    def _compute_reference_count(ref_count: int) -> float:
        """Compute reference count score."""
        return min(1.0, ref_count / 20.0)  # 20 references = max score

    @staticmethod
    def _compute_conversation_depth(depth: int) -> float:
        """Compute conversation depth score."""
        return min(1.0, depth / 10.0)  # 10 exchanges = max score

    @staticmethod
    def importance_label(score: float) -> str:
        """Get human-readable importance label.

        Args:
            score: importance score 0.0-1.0

        Returns:
            string label: critical, high, medium, low, trivial
        """
        if score >= 0.9:
            return "critical"
        elif score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.1:
            return "low"
        else:
            return "trivial"

    @staticmethod
    def classify_to_enum(score: float) -> Importance:
        """Convert score to Importance enum.

        Args:
            score: importance score 0.0-1.0

        Returns:
            Importance enum value
        """
        if score >= 0.9:
            return Importance.CRITICAL
        elif score >= 0.7:
            return Importance.HIGH
        elif score >= 0.4:
            return Importance.MEDIUM
        elif score >= 0.1:
            return Importance.LOW
        else:
            return Importance.TRIVIAL

