"""Memory Embedding System (C4 §13, §37)."""

from core.memory.embeddings.generator import EmbeddingGenerator
from core.memory.embeddings.store import EmbeddingStore

__all__ = ["EmbeddingGenerator", "EmbeddingStore"]