"""Tests for metrics module."""

import pytest
from datetime import datetime, timezone

from weather_copy_bot.metrics import (
    summarize_fills,
    calculate_sharpe,
    calculate_max_drawdown,
)
from weather_copy_bot.models import Fill, EquityPoint, Side


class TestMetrics:
    """Tests for metrics calculations."""

    def test_summarize_empty_fills(self):
        """Test summarizing empty fill list."""
        result = summarize_fills([], [], mode="backtest")
        
        assert result.trade_count == 0
        assert result.total_pnl == 0.0
        assert result.win_rate == 0.0

    def test_summarize_winning_trades(self):
        """Test summarizing all winning trades."""
        fills = [
            Fill(
                fill_id=f"fill-{i}",
                signal_id=f"sig-{i}",
                target_wallet="0x123",
                market_slug="test",
                side=Side.BUY,
                price=0.50,
                size_usd=100.0,
                fee_usd=0.20,
                pnl_usd=3.30,
                latency_ms=200,
                filled_at=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]
        
        result = summarize_fills(fills, [], mode="backtest")
        
        assert result.trade_count == 5
        assert result.total_pnl > 0
        assert result.win_rate == 100.0

    def test_sharpe_calculation(self):
        """Test Sharpe ratio calculation."""
        fills = [
            Fill(
                fill_id=f"fill-{i}",
                signal_id=f"sig-{i}",
                target_wallet="0x123",
                market_slug="test",
                side=Side.BUY,
                price=0.50,
                size_usd=100.0,
                fee_usd=0.20,
                pnl_usd=2.0,
                latency_ms=200,
                filled_at=datetime.now(timezone.utc),
            )
            for i in range(10)
        ]
        
        sharpe = calculate_sharpe(fills, starting_balance=10000.0)
        assert isinstance(sharpe, float)

    def test_max_drawdown(self):
        """Test max drawdown calculation."""
        equity = [
            EquityPoint(
                timestamp=datetime.now(timezone.utc),
                equity_usd=10000.0,
                pnl_usd=0.0,
                drawdown_pct=0.0,
            ),
            EquityPoint(
                timestamp=datetime.now(timezone.utc),
                equity_usd=10500.0,
                pnl_usd=500.0,
                drawdown_pct=0.0,
            ),
            EquityPoint(
                timestamp=datetime.now(timezone.utc),
                equity_usd=9800.0,
                pnl_usd=-200.0,
                drawdown_pct=-6.67,
            ),
        ]
        
        dd = calculate_max_drawdown(equity)
        assert dd == pytest.approx(-6.67, rel=0.1)
