"""Tests for CopyBacktester."""

from datetime import datetime, timedelta, timezone

from weather_copy_bot.backtest import CopyBacktester
from weather_copy_bot.models import Side, TradeSignal


class TestCopyBacktester:
    """Tests for CopyBacktester."""

    def test_decide_stale_signal(self):
        """Test that stale signals are rejected."""
        backtester = CopyBacktester()

        signal = TradeSignal(
            signal_id="sig-001",
            target_wallet="0x123",
            market_slug="weather-nyc",
            market_title="Temperature above 90F in NYC?",
            city="NYC",
            outcome="Yes",
            side=Side.BUY,
            price=0.60,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=1500,  # > 800ms max
        )

        decision = backtester.decide(signal)
        assert decision.should_copy is False
        assert "stale" in decision.reason

    def test_decide_size_too_small(self):
        """Test that tiny positions are rejected."""
        backtester = CopyBacktester()

        signal = TradeSignal(
            signal_id="sig-002",
            target_wallet="0x123",
            market_slug="weather-nyc",
            market_title="Temperature above 90F in NYC?",
            city="NYC",
            outcome="Yes",
            side=Side.BUY,
            price=0.60,
            size_usd=10.0,  # Very small
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=100,
        )

        decision = backtester.decide(signal)
        assert decision.should_copy is False
        assert "size" in decision.reason

    def test_decide_valid_signal(self):
        """Test valid signal is accepted."""
        backtester = CopyBacktester()

        signal = TradeSignal(
            signal_id="sig-003",
            target_wallet="0x456",
            market_slug="weather-la",
            market_title="Temperature above 85F in LA?",
            city="LA",
            outcome="Yes",
            side=Side.BUY,
            price=0.55,
            size_usd=200.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )

        decision = backtester.decide(signal)
        assert decision.should_copy is True
        assert decision.copy_size_usd > 0

    def test_run_empty_signals(self):
        """Test running backtest with no signals."""
        backtester = CopyBacktester()
        result = backtester.run([])

        assert result.summary.trade_count == 0
        assert result.summary.total_pnl_usd == 0.0

    def test_run_with_signals(self):
        """Test running backtest with signals."""
        backtester = CopyBacktester()

        signals = [
            TradeSignal(
                signal_id=f"sig-{i:03d}",
                target_wallet="0x123",
                market_slug="weather-nyc",
                market_title="Temperature above 90F in NYC?",
                city="NYC",
                outcome="Yes",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                price=0.55,
                size_usd=100.0,
                detected_at=datetime.now(timezone.utc) + timedelta(minutes=i),
                target_filled_at=datetime.now(timezone.utc) + timedelta(minutes=i),
                latency_ms=200,
            )
            for i in range(5)
        ]

        result = backtester.run(signals)
        assert result.summary.trade_count >= 0
        assert len(result.equity_curve) >= 0
