"""Tests for wallet filter."""

from datetime import datetime, timezone

from weather_copy_bot.live import WalletFilterConfig, WeatherWalletFilter
from weather_copy_bot.models import Side, TradeSignal


class TestWeatherWalletFilter:
    """Tests for WeatherWalletFilter."""

    def test_weather_signal_accepted(self):
        """Test that weather signals are accepted."""
        filter_ = WeatherWalletFilter()

        signal = TradeSignal(
            signal_id="sig-001",
            target_wallet="0x123",
            market_slug="weather-nyc-rain-aug-2024",
            market_title="Will it rain in NYC on August 15?",
            city="New York",
            outcome="Yes",
            side=Side.BUY,
            price=0.45,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )

        should_copy, _ = filter_.should_copy(signal)
        assert should_copy is True

    def test_non_weather_signal_rejected(self):
        """Test that non-weather signals are rejected."""
        filter_ = WeatherWalletFilter()

        signal = TradeSignal(
            signal_id="sig-002",
            target_wallet="0x456",
            market_slug="president-election-2024",
            market_title="Who will win the 2024 election?",
            city="USA",
            outcome="Democrat",
            side=Side.BUY,
            price=0.50,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )

        should_copy, reason = filter_.should_copy(signal)
        assert should_copy is False
        assert "no_weather_keyword" in reason

    def test_temperature_signal_accepted(self):
        """Test temperature-related signals are accepted."""
        filter_ = WeatherWalletFilter()

        signal = TradeSignal(
            signal_id="sig-003",
            target_wallet="0x789",
            market_slug="temp-texas-high-aug",
            market_title="Will Austin exceed 105°F on August 10?",
            city="Austin",
            outcome="Yes",
            side=Side.BUY,
            price=0.55,
            size_usd=50.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=150,
        )

        should_copy, reason = filter_.should_copy(signal)
        assert should_copy is True
        assert "temp" in reason or "temperature" in reason

    def test_hurricane_signal_accepted(self):
        """Test hurricane signals are accepted."""
        filter_ = WeatherWalletFilter()

        signal = TradeSignal(
            signal_id="sig-004",
            target_wallet="0xabc",
            market_slug="hurricane-florida-sept",
            market_title="Will a hurricane hit Florida in September?",
            city="Florida",
            outcome="Yes",
            side=Side.SELL,
            price=0.30,
            size_usd=75.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=300,
        )

        should_copy, _ = filter_.should_copy(signal)
        assert should_copy is True

    def test_stats_tracking(self):
        """Test that statistics are tracked."""
        config = WalletFilterConfig(track_filter_stats=True)
        filter_ = WeatherWalletFilter(config)

        weather_signal = TradeSignal(
            signal_id="sig-005",
            target_wallet="0xdef",
            market_slug="weather-la-snow",
            market_title="Will it snow in LA this winter?",
            city="Los Angeles",
            outcome="No",
            side=Side.BUY,
            price=0.10,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )

        filter_.should_copy(weather_signal)

        stats = filter_.get_stats()
        assert stats.total_signals == 1
        assert stats.allowed_signals == 1
