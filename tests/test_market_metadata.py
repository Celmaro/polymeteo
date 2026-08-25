"""Tests for market metadata enrichment."""
from __future__ import annotations

import pytest

from weather_copy_bot.analysis.market_metadata import (
    LiquidityMetrics,
    MarketMetadata,
    MarketMetadataEnricher,
    VolumeTrend,
)


@pytest.fixture
def sample_market_data():
    """Sample market data for testing."""
    return {
        "id": "test-market-123",
        "question": "Temperature in NYC on Jan 1st?",
        "description": "Will the temperature exceed 50F?",
        "createdAt": "2024-01-01T00:00:00Z",
        "volume24hr": "1500000",
        "volume": "5000000",
        "liquidity": "2500000",
        "creator": "0x1234567890abcdef1234567890abcdef12345678",
        "clobTokenIds": ["clob-1", "clob-2"],
    }


@pytest.fixture
def enricher():
    """Create a MarketMetadataEnricher instance for testing."""
    return MarketMetadataEnricher()


class TestMarketMetadata:
    """Test MarketMetadata dataclass."""

    def test_metadata_has_volume_trend(self, sample_market_data):
        """MarketMetadata should have volume trend."""
        metadata = MarketMetadata(
            volume_trend_24h=0.15,
            creator_reputation=0.75,
            liquidity_usd=2500000.0,
            market_age_hours=48,
            social_sentiment=0.3,
        )
        assert metadata.volume_trend_24h == 0.15

    def test_metadata_has_creator_reputation(self, sample_market_data):
        """MarketMetadata should have creator reputation score."""
        metadata = MarketMetadata(
            volume_trend_24h=0.15,
            creator_reputation=0.75,
            liquidity_usd=2500000.0,
            market_age_hours=48,
            social_sentiment=0.3,
        )
        assert metadata.creator_reputation == 0.75
        assert 0 <= metadata.creator_reputation <= 1

    def test_metadata_has_liquidity_usd(self, sample_market_data):
        """MarketMetadata should have liquidity in USD."""
        metadata = MarketMetadata(
            volume_trend_24h=0.15,
            creator_reputation=0.75,
            liquidity_usd=2500000.0,
            market_age_hours=48,
            social_sentiment=0.3,
        )
        assert metadata.liquidity_usd == 2500000.0

    def test_metadata_has_market_age_hours(self, sample_market_data):
        """MarketMetadata should have market age in hours."""
        metadata = MarketMetadata(
            volume_trend_24h=0.15,
            creator_reputation=0.75,
            liquidity_usd=2500000.0,
            market_age_hours=48,
            social_sentiment=0.3,
        )
        assert metadata.market_age_hours == 48

    def test_metadata_has_social_sentiment(self, sample_market_data):
        """MarketMetadata should have social sentiment."""
        metadata = MarketMetadata(
            volume_trend_24h=0.15,
            creator_reputation=0.75,
            liquidity_usd=2500000.0,
            market_age_hours=48,
            social_sentiment=0.3,
        )
        assert metadata.social_sentiment == 0.3
        assert -1 <= metadata.social_sentiment <= 1

    def test_metadata_social_sentiment_can_be_none(self, sample_market_data):
        """MarketMetadata social_sentiment can be None."""
        metadata = MarketMetadata(
            volume_trend_24h=0.0,
            creator_reputation=0.5,
            liquidity_usd=1000000.0,
            market_age_hours=24,
            social_sentiment=None,
        )
        assert metadata.social_sentiment is None


class TestLiquidityMetrics:
    """Test LiquidityMetrics dataclass."""

    def test_liquidity_metrics_has_bid_ask_spread(self):
        """LiquidityMetrics should have bid-ask spread."""
        metrics = LiquidityMetrics(bid_ask_spread_bps=25.0, depth_score=0.8)
        assert metrics.bid_ask_spread_bps == 25.0

    def test_liquidity_metrics_has_depth_score(self):
        """LiquidityMetrics should have depth score."""
        metrics = LiquidityMetrics(bid_ask_spread_bps=25.0, depth_score=0.8)
        assert metrics.depth_score == 0.8
        assert 0 <= metrics.depth_score <= 1

    def test_liquidity_metrics_defaults(self):
        """LiquidityMetrics should have sensible defaults."""
        metrics = LiquidityMetrics()
        assert metrics.bid_ask_spread_bps >= 0
        assert 0 <= metrics.depth_score <= 1


class TestVolumeTrend:
    """Test VolumeTrend dataclass."""

    def test_volume_trend_has_percent_change(self):
        """VolumeTrend should have percent change."""
        trend = VolumeTrend(percent_change_24h=15.5)
        assert trend.percent_change_24h == 15.5

    def test_volume_trend_defaults(self):
        """VolumeTrend should have default percent change."""
        trend = VolumeTrend()
        assert trend.percent_change_24h == 0.0


class TestMarketMetadataEnricher:
    """Test MarketMetadataEnricher class."""

    def test_enricher_initializes(self, enricher):
        """Enricher should initialize without errors."""
        assert enricher is not None

    @pytest.mark.asyncio
    async def test_enricher_enriches_market(self, enricher, sample_market_data):
        """Enricher should enrich market with metadata."""
        metadata = await enricher.enrich_market(sample_market_data)
        assert isinstance(metadata, MarketMetadata)

    @pytest.mark.asyncio
    async def test_enricher_calculates_volume_trend(self, enricher, sample_market_data):
        """Enricher should calculate volume trend from market data."""
        metadata = await enricher.enrich_market(sample_market_data)
        assert isinstance(metadata.volume_trend_24h, float)

    @pytest.mark.asyncio
    async def test_enricher_calculates_market_age(self, enricher, sample_market_data):
        """Enricher should calculate market age in hours."""
        metadata = await enricher.enrich_market(sample_market_data)
        assert metadata.market_age_hours >= 0

    @pytest.mark.asyncio
    async def test_enricher_handles_missing_volume(self, enricher):
        """Enricher should handle markets with missing volume data."""
        market = {
            "id": "test-market",
            "question": "Test?",
        }
        metadata = await enricher.enrich_market(market)
        assert isinstance(metadata, MarketMetadata)
        assert metadata.volume_trend_24h == 0.0

    @pytest.mark.asyncio
    async def test_enricher_calculates_liquidity_metrics(self, enricher, sample_market_data):
        """Enricher should calculate liquidity metrics."""
        metrics = await enricher.get_liquidity_metrics(sample_market_data)
        assert isinstance(metrics, LiquidityMetrics)

    @pytest.mark.asyncio
    async def test_enricher_calculates_volume_trend_obj(self, enricher, sample_market_data):
        """Enricher should calculate VolumeTrend object."""
        trend = await enricher.get_volume_trend(sample_market_data)
        assert isinstance(trend, VolumeTrend)
