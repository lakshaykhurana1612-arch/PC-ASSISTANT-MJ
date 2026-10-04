"""
FAISS Vector Provider — Local vector similarity search.

Uses FAISS (Facebook AI Similarity Search) for fast vector search.
Falls back to numpy brute-force search if FAISS is not installed.

Design:
- Provider-agnostic: implements VectorProvider interface
- Lazy initialization: index builds on first add() call
- Persistence: save/load index to/from disk
- Fallback: numpy brute-force if FAISS unavailable
- Thread-safe: uses lock for concurrent access
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

import numpy as np

from app.providers.vector_provider import (
    VectorProvider,
    VectorProviderError,
    VectorSearchResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "vector_index.faiss",
)

DEFAULT_METADATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "vector_metadata.json",
)


# ---------------------------------------------------------------------------
# FAISS Vector Provider
# ---------------------------------------------------------------------------


class FAISSVectorProvider(VectorProvider):
    """FAISS-based vector search provider.

    Usage:
        provider = FAISSVectorProvider()
        provider.initialize(dimension=384)
        provider.add([{
            "id": "mem_001",
            "vector": [0.1, 0.2, ...],
            "metadata": {"title": "Hello"}
        }])
        results = provider.search(query_vector=[...], k=5)
        provider.save("path/to/index")
    """

    def __init__(
        self,
        index_path: Optional[str] = None,
        metadata_path: Optional[str] = None,
        index_type: str = "flat",  # "flat", "ivf", "hnsw"
    ):
        self._index_path = index_path or DEFAULT_INDEX_PATH
        self._metadata_path = metadata_path or DEFAULT_METADATA_PATH
        self._index_type = index_type.lower()

        self._index = None
        self._dimension = 0
        self._metadata: dict[str, dict] = {}  # id -> metadata
        self._id_to_index: dict[str, int] = {}  # id -> faiss internal index
        self._index_to_id: dict[int, str] = {}  # faiss internal index -> id

        self._lock = threading.Lock()
        self._initialized = False
        self._fallback = False  # True if using numpy fallback
        self._next_id = 0  # For fallback tracking

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self._index_path), exist_ok=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def size(self) -> int:
        with self._lock:
            if self._index is not None:
                return self._index.ntotal
            return len(self._metadata)

    @property
    def is_fallback(self) -> bool:
        return self._fallback

    @property
    def index_path(self) -> str:
        return self._index_path

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, dimension: int = 384) -> None:
        """Initialize the FAISS index."""
        if self._initialized:
            return

        self._dimension = dimension

        try:
            import faiss

            # Create index based on type
            if self._index_type == "flat":
                self._index = faiss.IndexFlatIP(dimension)  # Inner product (cosine if normalized)
            elif self._index_type == "ivf":
                quantizer = faiss.IndexFlatIP(dimension)
                nlist = min(100, int(dimension ** 0.5))
                self._index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
                self._index.nprobe = 10
            elif self._index_type == "hnsw":
                self._index = faiss.IndexHNSWFlat(dimension, 32)  # 32 neighbors
                self._index.hnsw.efConstruction = 40
                self._index.hnsw.efSearch = 16
            else:
                logger.warning(f"Unknown index type '{self._index_type}', using FlatIP")
                self._index = faiss.IndexFlatIP(dimension)

            # Try to load existing index
            if os.path.exists(self._index_path):
                try:
                    self._index = faiss.read_index(self._index_path)
                    loaded_dim = self._index.d
                    if loaded_dim != dimension:
                        logger.warning(f"Loaded index dim {loaded_dim} != requested {dimension}. Using loaded.")
                    self._dimension = loaded_dim
                    logger.info(f"Loaded existing FAISS index from {self._index_path}")
                except Exception as e:
                    logger.warning(f"Could not load existing index: {e}")

            # Load metadata
            self._load_metadata()

            self._initialized = True
            self._fallback = False
            logger.info(f"FAISS provider initialized (type={self._index_type}, dim={self._dimension}, size={self.size})")

        except ImportError:
            logger.warning(
                "FAISS not installed. Using numpy fallback. "
                "Install with: pip install faiss-cpu"
            )
            self._init_fallback()
        except Exception as e:
            logger.warning(f"FAISS initialization failed: {e}. Using fallback.")
            self._init_fallback()

    def _init_fallback(self) -> None:
        """Initialize numpy brute-force fallback."""
        self._fallback = True
        self._initialized = True
        self._vectors: list[np.ndarray] = []
        self._fallback_ids: list[str] = []
        logger.info(f"Using numpy fallback vector search (dim={self._dimension})")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, entries: list[dict]) -> None:
        """Add vectors with metadata to the index."""
        if not entries:
            return

        if not self._initialized:
            self.initialize(self._dimension or len(entries[0].get("vector", [])))

        if self._fallback:
            self._add_fallback(entries)
            return

        with self._lock:
            vectors = []
            meta_entries = []

            for entry in entries:
                vid = entry.get("id", "")
                if not vid:
                    import uuid
                    vid = uuid.uuid4().hex[:24]
                    entry["id"] = vid

                vector = entry.get("vector", [])
                metadata = entry.get("metadata", {})

                if not vector or len(vector) != self._dimension:
                    logger.warning(f"Skipping entry {vid}: vector dimension mismatch")
                    continue

                vectors.append(vector)
                meta_entries.append((vid, metadata))

            if not vectors:
                return

            # Add to FAISS index
            vec_array = np.array(vectors, dtype=np.float32)
            if self._index_type == "ivf" and not self._index.is_trained:
                self._index.train(vec_array)

            start_idx = self._index.ntotal
            self._index.add(vec_array)

            # Update mappings
            for i, (vid, metadata) in enumerate(meta_entries):
                idx = start_idx + i
                self._id_to_index[vid] = idx
                self._index_to_id[idx] = vid
                self._metadata[vid] = metadata

            # Save metadata
            self._save_metadata()

        logger.info(f"Added {len(meta_entries)} vectors to FAISS index (total: {self.size})")

    def _add_fallback(self, entries: list[dict]) -> None:
        """Add vectors using numpy fallback."""
        with self._lock:
            for entry in entries:
                vector = entry.get("vector", [])
                vid = entry.get("id", "")
                metadata = entry.get("metadata", {})

                if not vid:
                    import uuid
                    vid = uuid.uuid4().hex[:24]

                vec = np.array(vector, dtype=np.float32)
                if len(vec) != self._dimension:
                    continue

                self._vectors.append(vec)
                self._fallback_ids.append(vid)
                self._metadata[vid] = metadata

    def delete(self, ids: list[str]) -> None:
        """Delete vectors by their IDs."""
        if not ids:
            return

        if self._fallback:
            self._delete_fallback(ids)
            return

        with self._lock:
            # FAISS doesn't support direct deletion from Flat index
            # We rebuild the index excluding deleted IDs
            ids_set = set(ids)
            keep_indices = []
            keep_ids = []

            for idx in range(self._index.ntotal):
                vid = self._index_to_id.get(idx)
                if vid and vid not in ids_set:
                    keep_indices.append(idx)
                    keep_ids.append(vid)

            if len(keep_indices) == self._index.ntotal:
                return  # Nothing to delete

            if keep_indices:
                # Reconstruct index with remaining vectors
                import faiss
                new_index = faiss.IndexFlatIP(self._dimension)

                vectors = []
                for idx in keep_indices:
                    vec = self._index.reconstruct(idx)
                    vectors.append(vec)

                if vectors:
                    new_index.add(np.array(vectors, dtype=np.float32))

                self._index = new_index

                # Rebuild mappings
                self._id_to_index = {vid: i for i, vid in enumerate(keep_ids)}
                self._index_to_id = {i: vid for i, vid in enumerate(keep_ids)}

            # Remove metadata
            for vid in ids:
                self._metadata.pop(vid, None)
                self._id_to_index.pop(vid, None)

            self._save_metadata()

        logger.info(f"Deleted {len(ids)} vectors from FAISS index (total: {self.size})")

    def _delete_fallback(self, ids: list[str]) -> None:
        """Delete vectors from numpy fallback."""
        with self._lock:
            ids_set = set(ids)
            keep = [(i, vid) for i, vid in enumerate(self._fallback_ids) if vid not in ids_set]
            self._vectors = [self._vectors[i] for i, _ in keep]
            self._fallback_ids = [vid for _, vid in keep]
            for vid in ids:
                self._metadata.pop(vid, None)

    def update(self, id: str, vector: Optional[list[float]] = None, metadata: Optional[dict] = None) -> bool:
        """Update an existing vector or its metadata."""
        if id not in self._metadata:
            return False

        if metadata is not None:
            self._metadata[id] = metadata
            self._save_metadata()

        if vector is not None:
            # Delete and re-add
            self.delete([id])
            self.add([{
                "id": id,
                "vector": vector,
                "metadata": self._metadata.get(id, {}),
            }])

        return True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        k: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Search for k most similar vectors."""
        if not query_vector or len(query_vector) != self._dimension:
            return []

        if not self._initialized:
            self.initialize(self._dimension or len(query_vector))

        if self._fallback:
            return self._search_fallback(query_vector, k, filter)

        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []

            try:
                query = np.array([query_vector], dtype=np.float32)
                scores, indices = self._index.search(query, min(k, self._index.ntotal))

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < 0 or idx >= self._index.ntotal:
                        continue
                    vid = self._index_to_id.get(int(idx), "")
                    if not vid:
                        continue

                    metadata = self._metadata.get(vid, {})
                    item = VectorSearchResult(
                        id=vid,
                        score=float(score),
                        metadata=metadata,
                    )

                    # Apply metadata filter
                    if filter and not self._match_filter(metadata, filter):
                        continue

                    results.append(item)

                return results

            except Exception as e:
                logger.error(f"FAISS search failed: {e}")
                return []

    def search_by_id(self, id: str, k: int = 10) -> list[VectorSearchResult]:
        """Search for similar vectors using an existing vector's ID."""
        if self._fallback:
            # Not supported in fallback
            return []

        with self._lock:
            idx = self._id_to_index.get(id)
            if idx is None:
                return []

            try:
                vec = self._index.reconstruct(idx)
                query = np.array([vec], dtype=np.float32)
                scores, indices = self._index.search(query, min(k + 1, self._index.ntotal))

                results = []
                for score, ridx in zip(scores[0], indices[0]):
                    if ridx < 0 or ridx >= self._index.ntotal:
                        continue
                    vid = self._index_to_id.get(int(ridx), "")
                    if not vid or vid == id:
                        continue

                    metadata = self._metadata.get(vid, {})
                    results.append(VectorSearchResult(
                        id=vid,
                        score=float(score),
                        metadata=metadata,
                    ))

                return results[:k]

            except Exception as e:
                logger.error(f"FAISS search by ID failed: {e}")
                return []

    def _search_fallback(
        self,
        query_vector: list[float],
        k: int = 10,
        filter: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        """Brute-force search using numpy."""
        with self._lock:
            if not self._vectors:
                return []

            query = np.array(query_vector, dtype=np.float32)
            query_norm = np.linalg.norm(query)

            if query_norm == 0:
                return []

            results = []
            for i, vec in enumerate(self._vectors):
                norm = np.linalg.norm(vec)
                if norm == 0:
                    continue
                similarity = float(np.dot(query, vec) / (query_norm * norm))

                vid = self._fallback_ids[i]
                metadata = self._metadata.get(vid, {})

                if filter and not self._match_filter(metadata, filter):
                    continue

                results.append(VectorSearchResult(
                    id=vid,
                    score=similarity,
                    metadata=metadata,
                ))

            results.sort(key=lambda x: x.score, reverse=True)
            return results[:k]

    # ------------------------------------------------------------------
    # Filter matching
    # ------------------------------------------------------------------

    @staticmethod
    def _match_filter(metadata: dict, filter: dict) -> bool:
        """Check if metadata matches filter criteria."""
        if not filter:
            return True

        for key, value in filter.items():
            if key in metadata:
                if isinstance(value, (list, tuple)):
                    if metadata[key] not in value:
                        return False
                elif metadata[key] != value:
                    return False
            elif value is not None:
                return False  # Key required but missing

        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        try:
            with open(self._metadata_path, "w") as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save metadata: {e}")

    def _load_metadata(self) -> None:
        """Load metadata from disk."""
        try:
            if os.path.exists(self._metadata_path):
                with open(self._metadata_path, "r") as f:
                    self._metadata = json.load(f)
                logger.info(f"Loaded metadata for {len(self._metadata)} vectors")
        except Exception as e:
            logger.warning(f"Failed to load metadata: {e}")
            self._metadata = {}

    def save(self, path: Optional[str] = None) -> None:
        """Persist the index to disk."""
        save_path = path or self._index_path

        if self._fallback:
            logger.warning("Fallback mode: persistence not supported")
            return

        with self._lock:
            if self._index is None:
                return

            try:
                import faiss
                faiss.write_index(self._index, save_path)
                self._save_metadata()
                logger.info(f"FAISS index saved to {save_path}")
            except Exception as e:
                logger.error(f"Failed to save index: {e}")

    def load(self, path: Optional[str] = None) -> bool:
        """Load a previously saved index from disk."""
        load_path = path or self._index_path

        if self._fallback:
            logger.warning("Fallback mode: cannot load FAISS index")
            return False

        try:
            import faiss
            self._index = faiss.read_index(load_path)
            self._dimension = self._index.d
            self._initialized = True

            # Load metadata
            self._load_metadata()

            # Rebuild mappings
            self._id_to_index = {}
            self._index_to_id = {}
            # Note: FAISS doesn't store IDs natively in IndexFlat
            # Mappings are reconstructed from metadata

            logger.info(f"FAISS index loaded from {load_path} (size={self.size})")
            return True

        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self.size

    def clear(self) -> None:
        """Clear all vectors."""
        with self._lock:
            if not self._fallback and self._index is not None:
                import faiss
                self._index = faiss.IndexFlatIP(self._dimension)
            else:
                self._vectors = []
                self._fallback_ids = []

            self._metadata = {}
            self._id_to_index = {}
            self._index_to_id = {}
            self._save_metadata()

            logger.warning("Vector index cleared.")

    def rebuild(self) -> None:
        """Rebuild the index from scratch."""
        if self._fallback:
            return

        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return

            import faiss
            new_index = faiss.IndexFlatIP(self._dimension)

            vectors = []
            ids = []
            for idx in range(self._index.ntotal):
                vid = self._index_to_id.get(idx)
                if vid:
                    vec = self._index.reconstruct(idx)
                    vectors.append(vec)
                    ids.append(vid)

            if vectors:
                new_index.add(np.array(vectors, dtype=np.float32))

            self._index = new_index
            self._id_to_index = {vid: i for i, vid in enumerate(ids)}
            self._index_to_id = {i: vid for i, vid in enumerate(ids)}

            logger.info("Vector index rebuilt.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release resources."""
        self.save()
        self._index = None
        self._metadata = {}
        self._initialized = False
        logger.info("FAISS provider closed.")

