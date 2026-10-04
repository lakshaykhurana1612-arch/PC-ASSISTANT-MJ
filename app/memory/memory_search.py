"""
Memory Search — Hybrid search engine for memories.

Combines multiple search strategies with rank fusion:
1. Vector search (semantic similarity via embeddings)
2. Keyword search (text matching via SQLite LIKE)
3. Importance score (precomputed importance)
4. Recency score (recency factor)
5. Pinned status (always boosted)

The final score is a weighted combination of all strategies.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from app.memory.models import MemoryEntry, MemoryQuery, MemoryResult
from app.memory.importance_scorer import ImportanceScorer
from app.providers.embedding_provider import EmbeddingProvider
from app.providers.vector_provider import VectorProvider, VectorSearchResult
from app.providers.memory_provider import MemoryProvider, MemoryFilter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search Configuration
# ---------------------------------------------------------------------------


@dataclass
class SearchConfig:
    """Configuration for hybrid search weights."""

    vector_weight: float = 0.35       # Semantic similarity weight
    keyword_weight: float = 0.25      # Keyword match weight
    importance_weight: float = 0.20   # Precomputed importance weight
    recency_weight: float = 0.10      # Recency weight
    pinned_boost: float = 0.20        # Boost for pinned memories
    min_score: float = 0.10           # Minimum combined score to include
    top_k_vector: int = 50            # Fetch more from vector for reranking
    top_k_keyword: int = 50           # Fetch more from keyword for reranking
    recency_half_life_hours: float = 72.0  # Recency decay


# ---------------------------------------------------------------------------
# Hybrid Search Engine
# ---------------------------------------------------------------------------


class MemorySearch:
    """Hybrid search engine that combines vector + keyword + importance + recency.

    Usage:
        search = MemorySearch(memory_provider, embedding_provider, vector_provider)
        results = search.search(MemoryQuery(text="resume file for rahul"))
        # Returns ranked MemoryResult list
    """

    def __init__(
        self,
        memory_provider: MemoryProvider,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_provider: Optional[VectorProvider] = None,
        config: Optional[SearchConfig] = None,
    ):
        self.memory_provider = memory_provider
        self.embedding_provider = embedding_provider
        self.vector_provider = vector_provider
        self.config = config or SearchConfig()
        self.importance_scorer = ImportanceScorer()

    # ------------------------------------------------------------------
    # Main search
    # ------------------------------------------------------------------

    def search(self, query: MemoryQuery) -> list[MemoryResult]:
        """Perform hybrid search across all memory stores.

        Args:
            query: MemoryQuery with search parameters

        Returns:
            list of MemoryResult ranked by combined score
        """
        if not query.text and not query.tags and query.importance_min == 0:
            return self._list_recent(query)

        results: dict[str, MemoryResult] = {}
        scores: dict[str, dict[str, float]] = {}

        # --- Vector Search ---
        if query.use_semantic and self.vector_provider and self.embedding_provider:
            vector_results = self._vector_search(query)
            for vr in vector_results:
                if vr.id not in scores:
                    scores[vr.id] = {}
                scores[vr.id]["vector"] = vr.score

        # --- Keyword Search ---
        if query.use_keyword:
            keyword_results = self._keyword_search(query)
            for kid, kscore in keyword_results:
                if kid not in scores:
                    scores[kid] = {}
                scores[kid]["keyword"] = kscore

        # --- Fetch full entries and compute scores ---
        all_ids = list(scores.keys())

        for mem_id in all_ids:
            entry_dict = self.memory_provider.read(mem_id)
            if not entry_dict:
                continue

            entry = MemoryEntry.from_dict(entry_dict)
            entry_scores = scores[mem_id]

            # Importance score
            importance = self.importance_scorer.calculate(entry)

            # Recency score
            recency = self._compute_recency(entry)

            # Combined score
            combined = self._combine_scores(
                vector_score=entry_scores.get("vector", 0.0),
                keyword_score=entry_scores.get("keyword", 0.0),
                importance=importance,
                recency=recency,
                pinned=entry.pinned,
            )

            if combined >= query.min_score:
                results[mem_id] = MemoryResult(
                    entry=entry,
                    score=combined,
                    vector_score=entry_scores.get("vector", 0.0),
                    keyword_score=entry_scores.get("keyword", 0.0),
                    importance_score=importance,
                    recency_score=recency,
                )

        # --- Sort and rank ---
        sorted_results = sorted(
            results.values(),
            key=lambda r: r.score,
            reverse=True,
        )

        for i, r in enumerate(sorted_results):
            r.rank = i + 1

        return sorted_results[: query.limit]

    # ------------------------------------------------------------------
    # Individual search strategies
    # ------------------------------------------------------------------

    def _vector_search(self, query: MemoryQuery) -> list[VectorSearchResult]:
        """Search using vector similarity."""
        try:
            query_vec = self.embedding_provider.embed_query(query.text)
            if not query_vec or all(v == 0.0 for v in query_vec):
                return []

            filter_dict = None
            if query.memory_type:
                filter_dict = {"memory_type": query.memory_type}

            results = self.vector_provider.search(
                query_vector=query_vec,
                k=self.config.top_k_vector,
                filter=filter_dict,
            )

            return results

        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

    def _keyword_search(self, query: MemoryQuery) -> list[tuple[str, float]]:
        """Search using keyword matching via SQLite."""
        try:
            query_text = query.text.strip()
            if not query_text:
                return []

            # Build MemoryFilter from query
            mfilter = MemoryFilter(
                memory_type=query.memory_type,
                importance_min=query.importance_min,
                tags=query.tags,
                limit=self.config.top_k_keyword,
            )

            # Do keyword search
            results = self.memory_provider.search(query_text, filter=mfilter)

            # Score results by keyword match density
            scored = []
            query_lower = query_text.lower()
            query_terms = set(query_lower.split())

            for entry in results:
                content = f"{entry.get('title', '')} {entry.get('content', '')} {entry.get('summary', '')}"
                content_lower = content.lower()

                # Count matching terms
                match_count = sum(1 for term in query_terms if term in content_lower)
                score = match_count / max(len(query_terms), 1)

                scored.append((entry.get("id", ""), score))

            return scored

        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
            return []

    def _list_recent(self, query: MemoryQuery) -> list[MemoryResult]:
        """List recent memories when no search query is provided."""
        try:
            mfilter = MemoryFilter(
                memory_type=query.memory_type,
                importance_min=query.importance_min,
                tags=query.tags,
                limit=query.limit,
                sort_by="created_at",
                sort_desc=True,
            )

            entries = self.memory_provider.list(mfilter)
            results = []

            for i, entry_dict in enumerate(entries):
                entry = MemoryEntry.from_dict(entry_dict)
                importance = self.importance_scorer.calculate(entry)
                results.append(MemoryResult(
                    entry=entry,
                    score=importance,
                    importance_score=importance,
                    rank=i + 1,
                ))

            return results

        except Exception as e:
            logger.warning(f"Recent list failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Score combination
    # ------------------------------------------------------------------

    def _combine_scores(
        self,
        vector_score: float,
        keyword_score: float,
        importance: float,
        recency: float,
        pinned: bool,
    ) -> float:
        """Combine multiple scores into a single relevance score."""
        total = (
            vector_score * self.config.vector_weight
            + keyword_score * self.config.keyword_weight
            + importance * self.config.importance_weight
            + recency * self.config.recency_weight
        )

        # Boost pinned memories
        if pinned:
            total += self.config.pinned_boost

        return min(total, 1.0)

    @staticmethod
    def _compute_recency(entry: MemoryEntry) -> float:
        """Compute recency score."""
        import time
        age_hours = (time.time() - entry.created_at) / 3600 if entry.created_at else 999
        half_life = SearchConfig.recency_half_life_hours
        return 2 ** (-age_hours / half_life)

    # ------------------------------------------------------------------
    # Search utilities
    # ------------------------------------------------------------------

    def find_similar(self, entry: MemoryEntry, k: int = 5) -> list[MemoryResult]:
        """Find memories similar to a given entry."""
        if not self.vector_provider:
            return []

        query = MemoryQuery(
            text=entry.title or entry.content[:200],
            limit=k,
        )
        return self.search(query)

    def search_by_type(self, memory_type: str, limit: int = 20) -> list[MemoryResult]:
        """Get all memories of a specific type."""
        query = MemoryQuery(
            memory_type=memory_type,
            limit=limit,
            use_semantic=False,
            use_keyword=False,
        )
        return self._list_recent(query)

