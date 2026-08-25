"""Vector embeddings for market context analysis."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EmbeddingModel(Enum):
    """Available embedding models."""

    SENTENCE_TRANSFORMER = "sentence-transformers/all-MiniLM-L6-v2"
    OPENAI_ADA = "text-embedding-ada-002"
    LOCAL = "local"


@dataclass
class MarketEmbedding:
    """Embedding vector for a market."""

    market_id: str
    embedding: list[float]
    model: EmbeddingModel
    created_at: float


@dataclass
class SimilarityResult:
    """Result of similarity search."""

    market_id: str
    question: str
    similarity: float


class VectorStore:
    """Vector store for market embeddings."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._embeddings: dict[str, list[float]] = {}
        self._market_questions: dict[str, str] = {}

    def add(self, market_id: str, embedding: list[float], question: str) -> None:
        """Add an embedding to the store."""
        if len(embedding) != self.dimension:
            raise ValueError(f"Embedding dimension {len(embedding)} != {self.dimension}")
        self._embeddings[market_id] = embedding
        self._market_questions[market_id] = question

    def search(
        self, query_embedding: list[float], top_k: int = 5
    ) -> list[SimilarityResult]:
        """Search for similar markets."""
        if not self._embeddings:
            return []

        results: list[SimilarityResult] = []
        for market_id, embedding in self._embeddings.items():
            similarity = self._cosine_similarity(query_embedding, embedding)
            results.append(
                SimilarityResult(
                    market_id=market_id,
                    question=self._market_questions.get(market_id, ""),
                    similarity=similarity,
                )
            )

        results.sort(key=lambda x: x.similarity, reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def get(self, market_id: str) -> list[float] | None:
        """Get embedding by market ID."""
        return self._embeddings.get(market_id)

    def delete(self, market_id: str) -> bool:
        """Delete an embedding."""
        if market_id in self._embeddings:
            del self._embeddings[market_id]
            self._market_questions.pop(market_id, None)
            return True
        return False


class MarketEmbeddingGenerator:
    """Generate embeddings for Polymarket markets."""

    def __init__(self, model: EmbeddingModel = EmbeddingModel.SENTENCE_TRANSFORMER) -> None:
        self.model = model
        self._model_instance: Any = None

    async def generate(self, text: str) -> list[float]:
        """Generate embedding for text."""
        if self.model == EmbeddingModel.SENTENCE_TRANSFORMER:
            return self._generate_sentence_transformer(text)
        if self.model == EmbeddingModel.LOCAL:
            return self._generate_local(text)
        return self._generate_random(text)

    def _generate_sentence_transformer(self, text: str) -> list[float]:
        """Generate embedding using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer
            if self._model_instance is None:
                self._model_instance = SentenceTransformer(self.model.value)
            return self._model_instance.encode(text).tolist()
        except ImportError:
            return self._generate_random(text)

    def _generate_local(self, text: str) -> list[float]:
        """Generate embedding using local model."""
        return self._generate_random(text)

    def _generate_random(self, text: str) -> list[float]:
        """Generate pseudo-embedding for testing."""
        import hashlib
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        import random
        random.seed(hash_val)
        return [random.uniform(-1, 1) for _ in range(384)]

    def get_dimension(self) -> int:
        """Get embedding dimension for current model."""
        if self.model == EmbeddingModel.OPENAI_ADA:
            return 1536
        return 384
