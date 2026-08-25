"""Tests for the database layer."""

from datetime import datetime, timezone

from weather_copy_bot.db.models import (
    Decision,
    Fill,
    Signal,
    Strategy,
)


class TestStrategyModel:
    """Tests for Strategy model."""

    def test_strategy_creation(self):
        """Test creating a strategy."""
        strategy = Strategy(
            name="test_strategy",
            version=1,
            copy_ratio=0.25,
            max_position_usd=250.0,
        )
        assert strategy.name == "test_strategy"
        assert strategy.version == 1
        assert strategy.copy_ratio == 0.25
        assert strategy.is_active is True

    def test_strategy_defaults(self):
        """Test default values."""
        strategy = Strategy(name="default_test")
        assert strategy.version == 1
        assert strategy.copy_ratio == 0.25
        assert strategy.max_position_usd == 250.0
        assert strategy.min_edge_bps == 50.0
        assert strategy.max_copy_latency_ms == 800


class TestSignalModel:
    """Tests for Signal model."""

    def test_signal_required_fields(self):
        """Test signal with required fields only."""
        signal = Signal(
            signal_id="sig-001",
            target_wallet="0x123",
            market_slug="weather-nyc-rain",
            side="BUY",
            price=0.55,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        assert signal.signal_id == "sig-001"
        assert signal.side == "BUY"
        assert signal.latency_ms == 200


class TestDecisionModel:
    """Tests for Decision model."""

    def test_decision_should_copy(self):
        """Test decision with should_copy=True."""
        decision = Decision(
            signal_id=1,
            strategy_id=1,
            should_copy=True,
            reason="copy",
            copy_size_usd=25.0,
            expected_slippage_bps=5.0,
        )
        assert decision.should_copy is True
        assert decision.copy_size_usd == 25.0

    def test_decision_should_not_copy(self):
        """Test decision with should_copy=False."""
        decision = Decision(
            signal_id=1,
            strategy_id=1,
            should_copy=False,
            reason="stale_signal:1500ms",
        )
        assert decision.should_copy is False


class TestFillModel:
    """Tests for Fill model."""

    def test_fill_calculation(self):
        """Test fill P&L calculation."""
        fill = Fill(
            decision_id=1,
            fill_id="fill-001",
            side="BUY",
            price=0.55,
            size_usd=100.0,
            fee_usd=0.20,
            pnl_usd=3.30,
            markout=0.035,
            latency_ms=200,
            filled_at=datetime.now(timezone.utc),
        )
        assert fill.pnl_usd > 0
        assert fill.fee_usd > 0
        assert fill.markout == 0.035
