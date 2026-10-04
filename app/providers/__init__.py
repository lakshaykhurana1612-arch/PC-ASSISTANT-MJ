"""
MJ Provider System — Abstract interfaces for swappable backends.

All providers follow the same pattern:
1. Abstract base class defines the interface
2. Concrete implementations provide the backend
3. Provider Manager (future) selects active provider at runtime

Providers:
- MemoryProvider: Storage backends (SQLite, PostgreSQL, MongoDB, Cloud)
- EmbeddingProvider: Embedding models (SentenceTransformer, OpenAI, Gemini, Ollama)
- VectorProvider: Vector databases (FAISS, Chroma, Pinecone, Weaviate)
"""

from app.providers.memory_provider import (
    MemoryProvider,
    MemoryProviderError,
    MemoryFilter,
)
from app.providers.embedding_provider import (
    EmbeddingProvider,
    EmbeddingProviderError,
)
from app.providers.vector_provider import (
    VectorProvider,
    VectorProviderError,
    VectorSearchResult,
)

__all__ = [
    "MemoryProvider",
    "MemoryProviderError",
    "MemoryFilter",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "VectorProvider",
    "VectorProviderError",
    "VectorSearchResult",
]

