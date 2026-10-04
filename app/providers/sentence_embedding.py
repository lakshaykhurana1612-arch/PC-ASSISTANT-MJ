"""
SentenceTransformer Embedding Provider.

Uses sentence-transformers models (all-MiniLM-L6-v2 by default) for text embeddings.
Falls back to a simple TF-IDF-like approach if sentence-transformers is not installed.

Design:
- Provider-agnostic: implements EmbeddingProvider interface
- Lazy loading: model loads on first embed() call
- Fallback: numpy-based average embedding if no model available
- Batched: supports batch embedding for efficiency
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import numpy as np

from app.providers.embedding_provider import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingDimensionError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default model
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "all-MiniLM-L6-v2"  # 384 dimensions, fast, good quality
DEFAULT_DIMENSION = 384


# ---------------------------------------------------------------------------
# SentenceTransformer Provider
# ---------------------------------------------------------------------------


class SentenceEmbeddingProvider(EmbeddingProvider):
    """SentenceTransformer-based embedding provider.

    Usage:
        provider = SentenceEmbeddingProvider()
        provider.initialize()
        vec = provider.embed("Hello Boss!")
        vecs = provider.embed_batch(["Hello", "World"])
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        max_length: int = 512,
        normalize: bool = True,
    ):
        self._model_name = model_name
        self._device = device
        self._max_length = max_length
        self._normalize = normalize
        self._model = None
        self._dimension = DEFAULT_DIMENSION
        self._initialized = False
        self._fallback = False  # True if using numpy fallback

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name if not self._fallback else f"{self._model_name}_fallback"

    @property
    def is_fallback(self) -> bool:
        return self._fallback

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Load the SentenceTransformer model."""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self._model_name}")
            start = time.time()

            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
            )

            # Set max sequence length
            if hasattr(self._model, "max_seq_length"):
                self._model.max_seq_length = self._max_length

            # Get dimension
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._initialized = True
            self._fallback = False

            elapsed = time.time() - start
            logger.info(f"Embedding model loaded in {elapsed:.1f}s (dim={self._dimension})")

        except ImportError:
            logger.warning(
                "sentence-transformers not installed. Using numpy fallback. "
                "Install with: pip install sentence-transformers"
            )
            self._init_fallback()
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}. Using fallback.")
            self._init_fallback()

    def _init_fallback(self) -> None:
        """Initialize numpy-based fallback embedding."""
        self._fallback = True
        self._initialized = True
        self._dimension = DEFAULT_DIMENSION
        logger.info(f"Using numpy fallback embedding (dim={self._dimension})")

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        if not text or not text.strip():
            return [0.0] * self._dimension

        if not self._initialized:
            self.initialize()

        if not self._fallback and self._model is not None:
            try:
                vec = self._model.encode(text, normalize_embeddings=self._normalize)
                return vec.tolist()
            except Exception as e:
                logger.error(f"Embedding failed: {e}")
                return self._fallback_embed(text)

        return self._fallback_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts at once."""
        if not texts:
            return []

        if not self._initialized:
            self.initialize()

        if not self._fallback and self._model is not None:
            try:
                vecs = self._model.encode(
                    texts,
                    normalize_embeddings=self._normalize,
                    show_progress_bar=False,
                )
                return [v.tolist() for v in vecs]
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                return [self._fallback_embed(t) for t in texts]

        return [self._fallback_embed(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        """Embed a search query.

        SentenceTransformer uses the same model for queries and documents.
        """
        return self.embed(query)

    def _fallback_embed(self, text: str) -> list[float]:
        """Simple bag-of-words fallback embedding.

        Creates a fixed-size vector from character n-gram frequencies.
        Not great but better than zero vectors.
        """
        text = text.lower().strip()
        if not text:
            return [0.0] * self._dimension

        # Simple hash-based feature vector
        vec = np.zeros(self._dimension, dtype=np.float32)
        words = text.split()

        for word in words[:50]:  # Limit words
            for i, char in enumerate(word[:10]):
                idx = (hash(char) % (self._dimension - 1))
                vec[idx] += 1.0 / (i + 1)

        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------

    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2:
            return 0.0

        try:
            a = np.array(vec1, dtype=np.float32)
            b = np.array(vec2, dtype=np.float32)

            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(np.dot(a, b) / (norm_a * norm_b))
        except Exception as e:
            logger.error(f"Similarity computation failed: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release the model."""
        self._model = None
        self._initialized = False
        logger.info("Embedding model released.")

    def __del__(self):
        self.close()

