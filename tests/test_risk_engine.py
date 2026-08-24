"""Tests for risk engine."""

import pytest
from datetime import datetime, timezone

from weather_copy_bot.live.risk_engine import (
    RiskEngine,
    RiskLimits,
    RiskCheck,
    Position,
    LiquidityChecker,
)
from weather_copy_bot.models import TradeSignal, Side


class TestRiskEngine:
    """Tests for RiskEngine."""

    def test_trade_passes(self):
        """Test a trade that passes all checks."""
        engine = RiskEngine()
        
        signal = TradeSignal(
            signal_id="sig-001",
            target_wallet="0x123",
            market_slug="weather-nyc-rain",
            market_title="Will it rain in NYC?",
            city="NYC",
            outcome="Yes",
            side=Side.BUY,
            price=0.50,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        
        check = engine.check_trade(
            signal=signal,
            size_usd=50.0,
            balance=10000.0,
            daily_pnl=0.0,
            positions=[],
        )
        
        assert check.passed is True
        assert check.rejected is False

    def test_trade_rejected_daily_loss(self):
        """Test rejection due to daily loss limit."""
        engine = RiskEngine(
            limits=RiskLimits(max_daily_loss_usd=500.0)
        )
        
        signal = TradeSignal(
            signal_id="sig-002",
            target_wallet="0x123",
            market_slug="weather-la-heat",
            market_title="Will LA exceed 100°F?",
            city="LA",
            outcome="Yes",
            side=Side.BUY,
            price=0.60,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=100,
        )
        
        check = engine.check_trade(
            signal=signal,
            size_usd=50.0,
            balance=10000.0,
            daily_pnl=-600.0,  # Exceeds limit
            positions=[],
        )
        
        assert check.rejected is True
        assert "daily_loss" in check.reason

    def test_trade_rejected_high_latency(self):
        """Test rejection due to high latency."""
        engine = RiskEngine(
            limits=RiskLimits(max_latency_ms=500)
        )
        
        signal = TradeSignal(
            signal_id="sig-003",
            target_wallet="0x456",
            market_slug="weather-texas-snow",
            market_title="Will Texas get snow?",
            city="Texas",
            outcome="No",
            side=Side.SELL,
            price=0.20,
            size_usd=50.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=1000,  # Too high
        )
        
        check = engine.check_trade(
            signal=signal,
            size_usd=50.0,
            balance=10000.0,
            daily_pnl=0.0,
            positions=[],
        )
        
        assert check.rejected is True
        assert "latency" in check.reason

    def test_position_size_adjusted(self):
        """Test that position size is adjusted to max."""
        engine = RiskEngine(
            limits=RiskLimits(max_trade_size_usd=100.0)
        )
        
        signal = TradeSignal(
            signal_id="sig-004",
            target_wallet="0x789",
            market_slug="weather-miami-hurricane",
            market_title="Hurricane in Miami?",
            city="Miami",
            outcome="Yes",
            side=Side.BUY,
            price=0.40,
            size_usd=200.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        
        check = engine.check_trade(
            signal=signal,
            size_usd=200.0,  # Exceeds max
            balance=10000.0,
            daily_pnl=0.0,
            positions=[],
        )
        
        assert check.passed is True
        assert check.adjustment == 100.0

    def test_circuit_breaker(self):
        """Test circuit breaker activation."""
        engine = RiskEngine(
            limits=RiskLimits(
                enable_circuit_breaker=True,
                circuit_breaker_threshold=0.10,  # 10%
            )
        )
        
        # Set peak balance and current balance that triggers drawdown
        engine._peak_balance = 10000.0
        
        signal = TradeSignal(
            signal_id="sig-005",
            target_wallet="0xabc",
            market_slug="weather-denver-snow",
            market_title="Denver snowfall?",
            city="Denver",
            outcome="Yes",
            side=Side.BUY,
            price=0.55,
            size_usd=50.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        
        check = engine.check_trade(
            signal=signal,
            size_usd=50.0,
            balance=8500.0,  # 15% drawdown
            daily_pnl=-1500.0,
            positions=[],
        )
        
        assert check.rejected is True
        assert "drawdown" in check.reason or "circuit_breaker" in check.reason

    def test_record_trade(self):
        """Test recording trade for daily counters."""
        engine = RiskEngine()
        initial_trades = engine._daily_trades
        
        engine.record_trade(pnl=10.0)
        
        assert engine._daily_trades == initial_trades + 1

    def test_day_reset(self):
        """Test that daily counters reset on new day."""
        engine = RiskEngine()
        engine._daily_trades = 10
        engine._daily_loss = -100.0
        engine._day_key = "2020-01-01"  # Old date
        
        # Trigger day reset
        engine._check_day_reset()
        
        assert engine._daily_trades == 0
        assert engine._daily_loss == 0.0


class TestLiquidityChecker:
    """Tests for LiquidityChecker."""

    def test_sufficient_depth(self):
        """Test with sufficient liquidity."""
        checker = LiquidityChecker(min_depth_usd=100.0)
        
        levels = [
            (0.50, 50.0),  # price, size
            (0.51, 40.0),
            (0.52, 30.0),
        ]
        
        sufficient, reason = checker.check_depth(levels, Side.BUY, 100.0)
        
        assert sufficient is True

    def test_insufficient_depth(self):
        """Test with insufficient liquidity."""
        checker = LiquidityChecker(min_depth_usd=100.0)
        
        levels = [
            (0.50, 20.0),
            (0.51, 30.0),
        ]
        
        sufficient, reason = checker.check_depth(levels, Side.BUY, 100.0)
        
        assert sufficient is False

    def test_estimate_slippage(self):
        """Test slippage estimation."""
        checker = LiquidityChecker()
        
        levels = [
            (0.50, 50.0),
            (0.51, 30.0),
            (0.52, 20.0),
        ]
        
        slippage = checker.estimate_slippage(levels, 80.0, Side.BUY)
        
        assert slippage > 0
        assert slippage < 100  # Should be reasonable
