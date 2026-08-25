"""Tests for market classifier module."""
from __future__ import annotations

from weather_copy_bot.market_classifier import (
    MarketCategory,
    MarketClassification,
    MarketClassifier,
    MarketFeatures,
    MarketResolution,
)


class TestMarketCategory:
    """Test MarketCategory enum."""

    def test_has_sports(self):
        """Should have sports category."""
        assert MarketCategory.SPORTS.value == "sports"

    def test_has_politics(self):
        """Should have politics category."""
        assert MarketCategory.POLITICS.value == "politics"

    def test_has_economics(self):
        """Should have economics category."""
        assert MarketCategory.ECONOMICS.value == "economics"

    def test_has_weather(self):
        """Should have weather category."""
        assert MarketCategory.WEATHER.value == "weather"

    def test_has_crypto(self):
        """Should have crypto category."""
        assert MarketCategory.CRYPTO.value == "crypto"


class TestMarketResolution:
    """Test MarketResolution enum."""

    def test_has_binary(self):
        """Should have binary resolution."""
        assert MarketResolution.BINARY.value == "binary"

    def test_has_multiple_choice(self):
        """Should have multiple choice resolution."""
        assert MarketResolution.MULTIPLE_CHOICE.value == "multiple_choice"


class TestMarketFeatures:
    """Test MarketFeatures dataclass."""

    def test_has_question(self):
        """Should have question field."""
        features = MarketFeatures(
            question="Will it rain?",
            description="Weather prediction",
            tags=["weather", "rain"],
            volume_24h=10000.0,
            liquidity=50000.0,
        )
        assert features.question == "Will it rain?"

    def test_has_tags(self):
        """Should have tags field."""
        features = MarketFeatures(
            question="Test?",
            description="",
            tags=["tag1", "tag2"],
            volume_24h=0.0,
            liquidity=0.0,
        )
        assert len(features.tags) == 2


class TestMarketClassifier:
    """Test MarketClassifier class."""

    def test_initializes(self):
        """Should initialize without errors."""
        classifier = MarketClassifier()
        assert classifier is not None

    def test_classify_sports(self):
        """Should classify sports markets."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Will the Lakers win the game?",
            description="NBA basketball match",
            tags=["nba", "basketball", "lakers"],
            volume_24h=50000.0,
            liquidity=100000.0,
        )
        result = classifier.classify(features)
        assert result.category == MarketCategory.SPORTS
        assert result.confidence > 0.0

    def test_classify_politics(self):
        """Should classify politics markets."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Will Biden win re-election?",
            description="2024 presidential election",
            tags=["election", "politics", "biden"],
            volume_24h=100000.0,
            liquidity=500000.0,
        )
        result = classifier.classify(features)
        assert result.category == MarketCategory.POLITICS

    def test_classify_weather(self):
        """Should classify weather markets."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Will it rain in NYC tomorrow?",
            description="Weather forecast",
            tags=["weather", "rain", "new york"],
            volume_24h=10000.0,
            liquidity=25000.0,
        )
        result = classifier.classify(features)
        assert result.category == MarketCategory.WEATHER

    def test_classify_crypto(self):
        """Should classify crypto markets."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Will Bitcoin exceed $100k?",
            description="Bitcoin price prediction",
            tags=["bitcoin", "crypto", "btc"],
            volume_24h=200000.0,
            liquidity=1000000.0,
        )
        result = classifier.classify(features)
        assert result.category == MarketCategory.CRYPTO

    def test_classify_unknown(self):
        """Should classify unknown markets as OTHER."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Random question",
            description="Nothing specific",
            tags=["random"],
            volume_24h=100.0,
            liquidity=100.0,
        )
        result = classifier.classify(features)
        assert result.category == MarketCategory.OTHER
        assert result.confidence < 0.5

    def test_classify_returns_features(self):
        """Should return classification with features."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Test?",
            description="Test description",
            tags=["test"],
            volume_24h=0.0,
            liquidity=0.0,
        )
        result = classifier.classify(features)
        assert result.features == features


class TestMarketClassifierResolution:
    """Test resolution type detection."""

    def test_binary_resolution(self):
        """Should detect binary resolution."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Will it happen?",
            description="Yes or no",
            tags=[],
            volume_24h=0.0,
            liquidity=0.0,
        )
        assert classifier.get_resolution_type(features) == MarketResolution.BINARY

    def test_multiple_choice_resolution(self):
        """Should detect multiple choice."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Which team wins the championship?",
            description="Pick the winner",
            tags=[],
            volume_24h=0.0,
            liquidity=0.0,
        )
        assert classifier.get_resolution_type(features) == MarketResolution.MULTIPLE_CHOICE

    def test_range_resolution(self):
        """Should detect range resolution."""
        classifier = MarketClassifier()
        features = MarketFeatures(
            question="Temperature range on launch day?",
            description="Prediction range",
            tags=[],
            volume_24h=0.0,
            liquidity=0.0,
        )
        assert classifier.get_resolution_type(features) == MarketResolution.RANGE


class TestMarketClassification:
    """Test MarketClassification dataclass."""

    def test_has_all_fields(self):
        """Should have all required fields."""
        features = MarketFeatures(
            question="Test?",
            description="",
            tags=[],
            volume_24h=0.0,
            liquidity=0.0,
        )
        classification = MarketClassification(
            category=MarketCategory.OTHER,
            confidence=0.5,
            subcategory="test_sub",
            features=features,
        )
        assert classification.category == MarketCategory.OTHER
        assert classification.confidence == 0.5
        assert classification.subcategory == "test_sub"
        assert classification.features == features
