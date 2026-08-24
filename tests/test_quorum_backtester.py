"""Tests for Quorum Backtester."""

import pytest
from datetime import datetime, timezone

from weather_copy_bot.engine.quorum_backtester import (
    QuorumBacktester,
    BacktestConfig,
    BacktestSignal,
    generate_synthetic_signals,
)
from weather_copy_bot.engine.quorum import WalletCategory


class TestQuorumBacktester:
    """Tests for QuorumBacktester."""

    def test_initialization(self):
        """Test backtester initialization."""
        config = BacktestConfig(
            min_quorum_count=2,
            min_weighted_score=2.0,
        )
        
        backtester = QuorumBacktester(config=config)
        
        assert backtester.config.min_quorum_count == 2
        assert backtester.config.min_weighted_score == 2.0

    def test_run_with_synthetic_signals(self):
        """Test running backtest with synthetic signals."""
        backtester = QuorumBacktester()
        
        signals = generate_synthetic_signals(num_signals=50, num_wallets=5, num_tokens=10)
        exit_prices = {f"TOKEN_{i}": 0.55 for i in range(10)}
        
        result = backtester.run(signals, exit_prices)
        
        assert result.total_signals == 50
        assert result.start_date is not None
        assert result.end_date is not None

    def test_quorum_hits_counting(self):
        """Test that quorum hits are counted correctly."""
        backtester = QuorumBacktester(
            config=BacktestConfig(min_quorum_count=2)
        )
        
        # Create signals that will trigger quorum
        signals = [
            BacktestSignal(
                signal_id="1",
                wallet_address="0x111",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.50,
                timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="2",
                wallet_address="0x222",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.52,
                timestamp=datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
            ),
        ]
        
        exit_prices = {"TOKEN1": 0.55}
        
        result = backtester.run(signals, exit_prices)
        
        assert result.quorum_hits == 1  # Should reach quorum

    def test_no_quorum_with_insufficient_signals(self):
        """Test no quorum when not enough signals."""
        backtester = QuorumBacktester(
            config=BacktestConfig(min_quorum_count=3)
        )
        
        # Only 2 signals but need 3
        signals = [
            BacktestSignal(
                signal_id="1",
                wallet_address="0x111",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.50,
                timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="2",
                wallet_address="0x222",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.52,
                timestamp=datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
            ),
        ]
        
        exit_prices = {"TOKEN1": 0.55}
        
        result = backtester.run(signals, exit_prices)
        
        assert result.quorum_hits == 0
        assert result.orders_executed == 0

    def test_pnl_calculation(self):
        """Test P&L calculation."""
        backtester = QuorumBacktester(
            config=BacktestConfig(min_quorum_count=2)
        )
        
        signals = [
            BacktestSignal(
                signal_id="1",
                wallet_address="0x111",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.50,
                timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="2",
                wallet_address="0x222",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.52,
                timestamp=datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
            ),
        ]
        
        # Exit price higher than avg entry = profit
        exit_prices = {"TOKEN1": 0.60}
        
        result = backtester.run(signals, exit_prices)
        
        assert result.orders_profitable == 1
        assert result.total_pnl_usd > 0

    def test_pnl_by_side(self):
        """Test P&L breakdown by side."""
        backtester = QuorumBacktester(
            config=BacktestConfig(min_quorum_count=2)
        )
        
        signals = [
            BacktestSignal(
                signal_id="1",
                wallet_address="0x111",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.50,
                timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="2",
                wallet_address="0x222",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN1",
                side="BUY",
                price=0.52,
                timestamp=datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="3",
                wallet_address="0x333",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN2",
                side="SELL",
                price=0.40,
                timestamp=datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc),
            ),
            BacktestSignal(
                signal_id="4",
                wallet_address="0x444",
                wallet_category=WalletCategory.SMART_BOT,
                token_id="TOKEN2",
                side="SELL",
                price=0.42,
                timestamp=datetime(2024, 1, 1, 12, 3, tzinfo=timezone.utc),
            ),
        ]
        
        exit_prices = {"TOKEN1": 0.60, "TOKEN2": 0.35}
        
        result = backtester.run(signals, exit_prices)
        
        assert "BUY" in result.pnl_by_side
        assert "SELL" in result.pnl_by_side

    def test_parameter_sweep(self):
        """Test parameter sweep."""
        backtester = QuorumBacktester()
        
        signals = generate_synthetic_signals(num_signals=20, num_wallets=5, num_tokens=5)
        exit_prices = {f"TOKEN_{i}": 0.55 for i in range(5)}
        
        param_grid = {
            "min_quorum_count": [2, 3],
            "window_seconds": [300, 600],
        }
        
        results = backtester.run_parameter_sweep(signals, exit_prices, param_grid)
        
        assert len(results) == 4  # 2 x 2 combinations
        # Results should be sorted by Sharpe ratio
        for i in range(len(results) - 1):
            assert results[i].sharpe_ratio >= results[i + 1].sharpe_ratio


class TestGenerateSyntheticSignals:
    """Tests for synthetic signal generation."""

    def test_generation(self):
        """Test synthetic signal generation."""
        signals = generate_synthetic_signals(
            num_signals=100,
            num_wallets=10,
            num_tokens=20,
        )
        
        assert len(signals) == 100
        # Should be sorted by timestamp
        for i in range(len(signals) - 1):
            assert signals[i].timestamp <= signals[i + 1].timestamp

    def test_unique_signal_ids(self):
        """Test that signal IDs are unique."""
        signals = generate_synthetic_signals(num_signals=50)
        
        ids = [s.signal_id for s in signals]
        assert len(ids) == len(set(ids))


class TestBacktestConfig:
    """Tests for BacktestConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = BacktestConfig()
        
        assert config.min_quorum_count == 2
        assert config.min_weighted_score == 2.0
        assert config.window_seconds == 600
        assert config.max_acceptable_price == 0.85
        assert config.include_wallet_filter is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = BacktestConfig(
            min_quorum_count=3,
            min_weighted_score=3.0,
            window_seconds=300,
        )
        
        assert config.min_quorum_count == 3
        assert config.min_weighted_score == 3.0
        assert config.window_seconds == 300
