"""Tests for vector embeddings module."""
from __future__ import annotations

import pytest

from weather_copy_bot.embeddings import (
    EmbeddingModel,
    MarketEmbedding,
    MarketEmbeddingGenerator,
    SimilarityResult,
    VectorStore,
)


class TestEmbeddingModel:
    """Test EmbeddingModel enum."""

    def test_has_sentence_transformer(self):
        """Should have sentence transformer model."""
        assert EmbeddingModel.SENTENCE_TRANSFORMER.value == "sentence-transformers/all-MiniLM-L6-v2"

    def test_has_openai_ada(self):
        """Should have OpenAI ada model."""
        assert EmbeddingModel.OPENAI_ADA.value == "text-embedding-ada-002"

    def test_has_local(self):
        """Should have local model."""
        assert EmbeddingModel.LOCAL.value == "local"


class TestMarketEmbedding:
    """Test MarketEmbedding dataclass."""

    def test_has_market_id(self):
        """Should have market_id field."""
        emb = MarketEmbedding(
            market_id="test123",
            embedding=[0.1, 0.2, 0.3],
            model=EmbeddingModel.LOCAL,
            created_at=1234567890.0,
        )
        assert emb.market_id == "test123"

    def test_has_embedding(self):
        """Should have embedding field."""
        emb = MarketEmbedding(
            market_id="test123",
            embedding=[0.1, 0.2, 0.3],
            model=EmbeddingModel.LOCAL,
            created_at=1234567890.0,
        )
        assert len(emb.embedding) == 3

    def test_has_model(self):
        """Should have model field."""
        emb = MarketEmbedding(
            market_id="test123",
            embedding=[0.1, 0.2, 0.3],
            model=EmbeddingModel.SENTENCE_TRANSFORMER,
            created_at=1234567890.0,
        )
        assert emb.model == EmbeddingModel.SENTENCE_TRANSFORMER


class TestVectorStore:
    """Test VectorStore class."""

    def test_initializes(self):
        """Should initialize with default dimension."""
        store = VectorStore()
        assert store.dimension == 384

    def test_custom_dimension(self):
        """Should initialize with custom dimension."""
        store = VectorStore(dimension=512)
        assert store.dimension == 512

    def test_add_embedding(self):
        """Should add embeddings to store."""
        store = VectorStore()
        embedding = [0.1] * 384
        store.add("market1", embedding, "Will it rain?")
        assert store.get("market1") == embedding

    def test_add_wrong_dimension_raises(self):
        """Should raise on wrong dimension."""
        store = VectorStore()
        with pytest.raises(ValueError, match="Embedding dimension"):
            store.add("market1", [0.1, 0.2], "Will it rain?")

    def test_search_empty(self):
        """Should return empty on empty store."""
        store = VectorStore()
        results = store.search([0.1] * 384)
        assert results == []

    def test_search_returns_results(self):
        """Should return similar markets."""
        store = VectorStore()
        emb1 = [1.0] * 384
        emb2 = [0.0] * 384
        store.add("market1", emb1, "Yes question")
        store.add("market2", emb2, "No question")
        results = store.search(emb1, top_k=1)
        assert len(results) == 1
        assert results[0].market_id == "market1"

    def test_delete_embedding(self):
        """Should delete embeddings."""
        store = VectorStore()
        store.add("market1", [0.1] * 384, "Test")
        assert store.delete("market1") is True
        assert store.get("market1") is None

    def test_delete_nonexistent(self):
        """Should return False for nonexistent."""
        store = VectorStore()
        assert store.delete("nonexistent") is False


class TestSimilarityResult:
    """Test SimilarityResult dataclass."""

    def test_has_fields(self):
        """Should have all fields."""
        result = SimilarityResult(
            market_id="m1",
            question="Test?",
            similarity=0.95,
        )
        assert result.market_id == "m1"
        assert result.question == "Test?"
        assert result.similarity == 0.95


class TestMarketEmbeddingGenerator:
    """Test MarketEmbeddingGenerator class."""

    def test_initializes(self):
        """Should initialize with model."""
        gen = MarketEmbeddingGenerator()
        assert gen.model == EmbeddingModel.SENTENCE_TRANSFORMER

    def test_custom_model(self):
        """Should initialize with custom model."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.LOCAL)
        assert gen.model == EmbeddingModel.LOCAL

    def test_get_dimension_default(self):
        """Should return correct dimension for model."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.SENTENCE_TRANSFORMER)
        assert gen.get_dimension() == 384

    def test_get_dimension_ada(self):
        """Should return 1536 for ada."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.OPENAI_ADA)
        assert gen.get_dimension() == 1536

    @pytest.mark.asyncio
    async def test_generate_returns_list(self):
        """Should return embedding list."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.LOCAL)
        embedding = await gen.generate("Test market question")
        assert isinstance(embedding, list)
        assert len(embedding) == 384

    @pytest.mark.asyncio
    async def test_generate_consistent(self):
        """Same text should produce same embedding."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.LOCAL)
        emb1 = await gen.generate("Will it rain tomorrow?")
        emb2 = await gen.generate("Will it rain tomorrow?")
        assert emb1 == emb2

    @pytest.mark.asyncio
    async def test_generate_different_texts(self):
        """Different texts should produce different embeddings."""
        gen = MarketEmbeddingGenerator(EmbeddingModel.LOCAL)
        emb1 = await gen.generate("Will it rain tomorrow?")
        emb2 = await gen.generate("Who will win the election?")
        assert emb1 != emb2
