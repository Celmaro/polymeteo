"""Tests for Pydantic domain models."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from weather_copy_bot.models import (
    CityBreakdown,
    CopyDecision,
    DashboardPayload,
    EquityPoint,
    Fill,
    LatencyBucket,
    PerformanceSummary,
    Side,
    TradeSignal,
    WalletScorecard,
)


class TestTradeSignal:
    """Test TradeSignal model."""

    def test_valid_signal(self):
        now = datetime.now(timezone.utc)
        signal = TradeSignal(
            signal_id="sig-1",
            target_wallet="0xabc",
            market_slug="test-market",
            market_title="Test Market?",
            city="Tokyo",
            outcome="Yes",
            side=Side.BUY,
            price=0.55,
            size_usd=100.0,
            detected_at=now,
            target_filled_at=now,
            latency_ms=350,
        )
        assert signal.signal_id == "sig-1"
        assert signal.side == Side.BUY
        assert signal.price == 0.55

    def test_signal_sell_side(self):
        signal = TradeSignal(
            signal_id="sig-2",
            target_wallet="0xdef",
            market_slug="test",
            market_title="Test?",
            city="London",
            outcome="No",
            side=Side.SELL,
            price=0.45,
            size_usd=50.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        assert signal.side == Side.SELL

    def test_signal_optional_token_id(self):
        signal = TradeSignal(
            signal_id="sig-3",
            target_wallet="0xghi",
            market_slug="test",
            market_title="Test?",
            city="Global",
            outcome="Yes",
            side=Side.BUY,
            price=0.5,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=300,
            token_id=None,
        )
        assert signal.token_id is None

    def test_signal_invalid_side_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignal(
                signal_id="sig-4",
                target_wallet="0xjkl",
                market_slug="test",
                market_title="Test?",
                city="NYC",
                outcome="Yes",
                side="INVALID",
                price=0.5,
                size_usd=100.0,
                detected_at=datetime.now(timezone.utc),
                target_filled_at=datetime.now(timezone.utc),
                latency_ms=300,
            )


class TestFill:
    """Test Fill model."""

    def test_valid_fill(self):
        now = datetime.now(timezone.utc)
        fill = Fill(
            fill_id="fill-1",
            signal_id="sig-1",
            target_wallet="0xabc",
            market_slug="test",
            market_title="Test?",
            city="Tokyo",
            outcome="Yes",
            side=Side.BUY,
            price=0.55,
            size_usd=100.0,
            fee_usd=0.25,
            pnl_usd=15.5,
            latency_ms=350,
            filled_at=now,
            mode="paper",
        )
        assert fill.fill_id == "fill-1"
        assert fill.pnl_usd == 15.5
        assert fill.mode == "paper"


class TestCopyDecision:
    """Test CopyDecision model."""

    def test_reject_decision(self):
        signal = TradeSignal(
            signal_id="sig-1",
            target_wallet="0xabc",
            market_slug="test",
            market_title="Test?",
            city="Tokyo",
            outcome="Yes",
            side=Side.BUY,
            price=0.5,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=500,
        )
        decision = CopyDecision(
            signal=signal,
            should_copy=False,
            reason="Signal too stale",
        )
        assert decision.should_copy is False
        assert decision.copy_size_usd == 0.0

    def test_accept_decision(self):
        signal = TradeSignal(
            signal_id="sig-2",
            target_wallet="0xdef",
            market_slug="test",
            market_title="Test?",
            city="London",
            outcome="Yes",
            side=Side.BUY,
            price=0.42,
            size_usd=100.0,
            detected_at=datetime.now(timezone.utc),
            target_filled_at=datetime.now(timezone.utc),
            latency_ms=200,
        )
        decision = CopyDecision(
            signal=signal,
            should_copy=True,
            reason="Fresh signal",
            copy_size_usd=25.0,
            expected_slippage_bps=2.5,
        )
        assert decision.should_copy is True
        assert decision.copy_size_usd == 25.0


class TestWalletScorecard:
    """Test WalletScorecard model."""

    def test_valid_scorecard(self):
        card = WalletScorecard(
            wallet="0xabc123",
            alias="0xabc...c123",
            total_pnl_usd=1500.0,
            win_rate=68.5,
            trade_count=150,
            avg_latency_ms=285.0,
            sharpe=1.85,
            max_drawdown_pct=8.2,
            profit_factor=2.3,
            specialty_cities=["Tokyo", "London", "NYC"],
            consistency_score=82.0,
            copy_recommendation="PRIMARY",
        )
        assert card.total_pnl_usd == 1500.0
        assert card.copy_recommendation == "PRIMARY"
        assert len(card.specialty_cities) == 3

    def test_scorecard_default_specialties(self):
        card = WalletScorecard(
            wallet="0xdef456",
            alias="0xdef...f456",
            total_pnl_usd=200.0,
            win_rate=55.0,
            trade_count=30,
            avg_latency_ms=350.0,
            sharpe=0.9,
            max_drawdown_pct=15.0,
            profit_factor=1.5,
            consistency_score=65.0,
            copy_recommendation="WATCHLIST",
        )
        assert card.specialty_cities == []


class TestPerformanceSummary:
    """Test PerformanceSummary model."""

    def test_valid_summary(self):
        summary = PerformanceSummary(
            mode="paper",
            starting_balance=10000.0,
            ending_balance=11250.0,
            total_pnl_usd=1250.0,
            total_return_pct=12.5,
            win_rate=62.0,
            trade_count=85,
            avg_latency_ms=295.0,
            median_latency_ms=280.0,
            sharpe=1.45,
            sortino=1.82,
            max_drawdown_pct=6.5,
            profit_factor=2.1,
            best_trade_usd=85.0,
            worst_trade_usd=-25.0,
            avg_copy_edge_bps=3.2,
        )
        assert summary.mode == "paper"
        assert summary.total_return_pct == 12.5


class TestEquityPoint:
    """Test EquityPoint model."""

    def test_valid_equity_point(self):
        point = EquityPoint(
            timestamp=datetime.now(timezone.utc),
            equity_usd=10500.0,
            pnl_usd=500.0,
            drawdown_pct=2.5,
        )
        assert point.equity_usd == 10500.0


class TestCityBreakdown:
    """Test CityBreakdown model."""

    def test_valid_city_breakdown(self):
        breakdown = CityBreakdown(
            city="Tokyo",
            trade_count=45,
            pnl_usd=820.0,
            win_rate=68.9,
        )
        assert breakdown.city == "Tokyo"
        assert breakdown.trade_count == 45


class TestLatencyBucket:
    """Test LatencyBucket model."""

    def test_valid_latency_bucket(self):
        bucket = LatencyBucket(
            bucket="200-400ms",
            trade_count=30,
            avg_pnl_usd=12.5,
            win_rate=70.0,
        )
        assert bucket.bucket == "200-400ms"


class TestDashboardPayload:
    """Test DashboardPayload model."""

    def test_empty_payload(self):
        payload = DashboardPayload(
            generated_at=datetime.now(timezone.utc),
            headline=PerformanceSummary(
                mode="live",
                starting_balance=10000.0,
                ending_balance=10000.0,
                total_pnl_usd=0.0,
                total_return_pct=0.0,
                win_rate=0.0,
                trade_count=0,
                avg_latency_ms=0.0,
                median_latency_ms=0.0,
                sharpe=0.0,
                sortino=0.0,
                max_drawdown_pct=0.0,
                profit_factor=0.0,
                best_trade_usd=0.0,
                worst_trade_usd=0.0,
                avg_copy_edge_bps=0.0,
            ),
            paper=PerformanceSummary(
                mode="paper",
                starting_balance=10000.0,
                ending_balance=10000.0,
                total_pnl_usd=0.0,
                total_return_pct=0.0,
                win_rate=0.0,
                trade_count=0,
                avg_latency_ms=0.0,
                median_latency_ms=0.0,
                sharpe=0.0,
                sortino=0.0,
                max_drawdown_pct=0.0,
                profit_factor=0.0,
                best_trade_usd=0.0,
                worst_trade_usd=0.0,
                avg_copy_edge_bps=0.0,
            ),
            backtest=PerformanceSummary(
                mode="backtest",
                starting_balance=10000.0,
                ending_balance=10000.0,
                total_pnl_usd=0.0,
                total_return_pct=0.0,
                win_rate=0.0,
                trade_count=0,
                avg_latency_ms=0.0,
                median_latency_ms=0.0,
                sharpe=0.0,
                sortino=0.0,
                max_drawdown_pct=0.0,
                profit_factor=0.0,
                best_trade_usd=0.0,
                worst_trade_usd=0.0,
                avg_copy_edge_bps=0.0,
            ),
            wallets=[],
            equity_curve=[],
            paper_equity=[],
            backtest_equity=[],
            recent_fills=[],
            city_breakdown=[],
            latency_buckets=[],
            copy_funnel={},
            engine_status={},
        )
        assert payload.generated_at is not None
        assert payload.headline.mode == "live"
