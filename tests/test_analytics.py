"""Tests for DuckDB analytics layer."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules["sqlalchemy"] = MagicMock()

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


from weather_copy_bot.analytics import (  # noqa: E402
    AnalyticsEngine,
    MarketAnalytics,
    PerformanceMetrics,
    VolumeStats,
)


class TestPerformanceMetrics:
    """Test PerformanceMetrics dataclass."""

    def test_metrics_has_sharpe_ratio(self):
        """Metrics should have sharpe_ratio field."""
        metrics = PerformanceMetrics(sharpe_ratio=1.5)
        assert metrics.sharpe_ratio == 1.5

    def test_metrics_has_win_rate(self):
        """Metrics should have win_rate field."""
        metrics = PerformanceMetrics(win_rate=0.65)
        assert metrics.win_rate == 0.65

    def test_metrics_has_total_pnl(self):
        """Metrics should have total_pnl field."""
        metrics = PerformanceMetrics(total_pnl=1500.0)
        assert metrics.total_pnl == 1500.0

    def test_metrics_defaults(self):
        """Metrics should have default values."""
        metrics = PerformanceMetrics()
        assert metrics.sharpe_ratio == 0.0
        assert metrics.win_rate == 0.0
        assert metrics.total_pnl == 0.0


class TestVolumeStats:
    """Test VolumeStats dataclass."""

    def test_stats_has_total_volume(self):
        """Stats should have total_volume field."""
        stats = VolumeStats(total_volume=1000000.0)
        assert stats.total_volume == 1000000.0

    def test_stats_has_avg_daily_volume(self):
        """Stats should have avg_daily_volume field."""
        stats = VolumeStats(avg_daily_volume=50000.0)
        assert stats.avg_daily_volume == 50000.0

    def test_stats_defaults(self):
        """Stats should have default values."""
        stats = VolumeStats()
        assert stats.total_volume == 0.0
        assert stats.avg_daily_volume == 0.0


class TestMarketAnalytics:
    """Test MarketAnalytics dataclass."""

    def test_analytics_has_market_id(self):
        """Analytics should have market_id field."""
        analytics = MarketAnalytics(market_id="test-123")
        assert analytics.market_id == "test-123"

    def test_analytics_has_price_stats(self):
        """Analytics should have price_stats field."""
        analytics = MarketAnalytics(
            market_id="test-123",
            price_stats={"mean": 0.55, "std": 0.05},
        )
        assert analytics.price_stats["mean"] == 0.55

    def test_analytics_defaults(self):
        """Analytics should have default values."""
        analytics = MarketAnalytics()
        assert analytics.market_id == ""
        assert analytics.price_stats is None


class TestAnalyticsEngine:
    """Test AnalyticsEngine class."""

    def test_engine_initializes(self):
        """Engine should initialize without errors."""
        engine = AnalyticsEngine()
        assert engine is not None

    def test_engine_can_be_created_with_db_path(self):
        """Engine should accept a custom database path."""
        engine = AnalyticsEngine(db_path=":memory:")
        assert engine.db_path == ":memory:"

    def test_engine_has_query_method(self):
        """Engine should have query method."""
        engine = AnalyticsEngine()
        assert hasattr(engine, "query")

    def test_engine_has_get_market_analytics_method(self):
        """Engine should have get_market_analytics method."""
        engine = AnalyticsEngine()
        assert hasattr(engine, "get_market_analytics")

    def test_engine_has_get_performance_metrics_method(self):
        """Engine should have get_performance_metrics method."""
        engine = AnalyticsEngine()
        assert hasattr(engine, "get_performance_metrics")

    def test_engine_has_get_volume_stats_method(self):
        """Engine should have get_volume_stats method."""
        engine = AnalyticsEngine()
        assert hasattr(engine, "get_volume_stats")

    def test_engine_has_load_parquet_method(self):
        """Engine should have load_parquet method."""
        engine = AnalyticsEngine()
        assert hasattr(engine, "load_parquet")
