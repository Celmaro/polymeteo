"""Market classifier for categorizing Polymarket markets."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketCategory(Enum):
    """Market category classification."""

    SPORTS = "sports"
    POLITICS = "politics"
    ECONOMICS = "economics"
    SCIENCE = "science"
    ENTERTAINMENT = "entertainment"
    WEATHER = "weather"
    CRYPTO = "crypto"
    OTHER = "other"


class MarketResolution(Enum):
    """How the market resolves."""

    BINARY = "binary"
    MULTIPLE_CHOICE = "multiple_choice"
    RANGE = "range"
    STAKES_SPLIT = "staking_split"


@dataclass
class MarketFeatures:
    """Features extracted from a market for classification."""

    question: str
    description: str
    tags: list[str]
    volume_24h: float
    liquidity: float


@dataclass
class MarketClassification:
    """Result of market classification."""

    category: MarketCategory
    confidence: float
    subcategory: str | None
    features: MarketFeatures


class MarketClassifier:
    """Classifier for Polymarket markets."""

    def __init__(self) -> None:
        self._category_keywords: dict[MarketCategory, list[str]] = {
            MarketCategory.SPORTS: [
                "game", "match", "win", "lose", "score", "player", "team",
                "championship", "tournament", "league", "season",
            ],
            MarketCategory.POLITICS: [
                "election", "vote", "president", "congress", "senate",
                "parliament", "party", "campaign", "polling", "re-election",
            ],
            MarketCategory.ECONOMICS: [
                "inflation", "gdp", "unemployment", "interest", "recession",
                "fed", "rate", "economy", "market", "stock", "index",
            ],
            MarketCategory.SCIENCE: [
                "research", "study", "trial", "fda", "approval", "discovery",
                "experiment", "space", "mission", "launch",
            ],
            MarketCategory.ENTERTAINMENT: [
                "award", "oscar", "grammy", "movie", "album", "show",
                "series", "premiere", "release", "box office",
            ],
            MarketCategory.WEATHER: [
                "rain", "snow", "hurricane", "storm", "temperature", "weather",
                "flood", "drought", "climate", "forecast",
            ],
            MarketCategory.CRYPTO: [
                "bitcoin", "btc", "eth", "crypto", "blockchain", "defi",
                "nft", "token", "exchange", "wallet",
            ],
        }

    def classify(self, features: MarketFeatures) -> MarketClassification:
        """Classify a market based on its features."""
        text = f"{features.question} {features.description} {' '.join(features.tags)}".lower()

        scores: dict[MarketCategory, float] = {}
        for category, keywords in self._category_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            scores[category] = score

        if max(scores.values()) == 0:
            return MarketClassification(
                category=MarketCategory.OTHER,
                confidence=0.1,
                subcategory=None,
                features=features,
            )

        best_category = max(scores, key=scores.get)
        confidence = scores[best_category] / (scores[best_category] + 2)

        return MarketClassification(
            category=best_category,
            confidence=min(0.95, confidence),
            subcategory=self._extract_subcategory(text),
            features=features,
        )

    def _extract_subcategory(self, text: str) -> str | None:
        """Extract subcategory from text."""
        if "nba" in text or "nfl" in text or "mlb" in text:
            return "us_sports"
        if "president" in text:
            return "presidential"
        if "congress" in text or "senate" in text:
            return "legislative"
        if "temperature" in text or "forecast" in text:
            return "meteorological"
        return None

    def get_resolution_type(self, features: MarketFeatures) -> MarketResolution:
        """Determine market resolution type."""
        text = f"{features.question} {features.description}".lower()

        if any(word in text for word in ["will", "yes", "no", "happen", "occur"]):
            return MarketResolution.BINARY
        if any(word in text for word in ["which", "who", "what percent"]):
            return MarketResolution.MULTIPLE_CHOICE
        if any(word in text for word in ["range", "between", "more than", "less than"]):
            return MarketResolution.RANGE
        return MarketResolution.STAKES_SPLIT
