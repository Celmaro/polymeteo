"""Tests for the equal-weight QuorumBacktester."""

from datetime import datetime, timezone

import pytest

from weather_copy_bot.engine.quorum_backtester import (
    BacktestConfig,
    BacktestSignal,
    QuorumBacktester,
    generate_synthetic_signals,
)

BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bt_signal(
    signal_id: str,
    wallet: str,
    token: str = "T1",
    side: str = "BUY",
    price: float = 0.50,
    size_usd: float = 0.0,
    offset_seconds: float = 0.0,
) -> BacktestSignal:
    return BacktestSignal(
        signal_id=signal_id,
        wallet_address=wallet,
        token_id=token,
        side=side,
        price=price,
        size_usd=size_usd,
        timestamp=datetime.fromtimestamp(BASE_TS.timestamp() + offset_seconds, tz=timezone.utc),
    )


def two_wallet_hit_signals(token: str = "T1") -> list[BacktestSignal]:
    """VWAP of these votes is (0.40*300 + 0.60*100) / 400 = 0.45."""
    return [
        bt_signal("s1", "0xaaa", token=token, price=0.40, size_usd=300.0),
        bt_signal("s2", "0xbbb", token=token, price=0.60, size_usd=100.0, offset_seconds=10),
    ]


class TestBacktestConfig:
    """Config carries only count/price knobs; weighted-score era is gone."""

    def test_defaults_are_equal_weight(self):
        config = BacktestConfig()

        assert config.min_quorum_count == 2
        assert config.window_seconds == 600
        assert config.max_acceptable_price == 0.85
        assert not hasattr(config, "min_weighted_score")
        assert not hasattr(config, "max_slippage_bps")

    def test_custom_config_propagates_to_quorum_engine(self):
        config = BacktestConfig(
            min_quorum_count=3,
            window_seconds=900,
            max_acceptable_price=0.70,
        )
        backtester = QuorumBacktester(config=config)

        assert backtester.config is config
        assert backtester._quorum_engine.min_quorum_count == 3
        assert backtester._quorum_engine.window_seconds == 900
        assert backtester._quorum_engine.max_acceptable_price == 0.70


class TestBacktestRun:
    """Consensus hits execute one order at the VWAP entry price."""

    def test_two_wallet_consensus_produces_one_profitable_order(self):
        backtester = QuorumBacktester(config=BacktestConfig())

        result = backtester.run(two_wallet_hit_signals(), {"T1": 0.80})

        assert result.total_signals == 2
        assert result.quorum_hits == 1
        assert result.quorum_misses == 1
        assert result.orders_executed == 1
        assert result.orders_profitable == 1
        expected_pnl = 100.0 * (0.80 - 0.45) / 0.45
        assert result.total_pnl_usd == pytest.approx(expected_pnl)
        assert result.pnl_by_side["BUY"] == pytest.approx(expected_pnl)
        assert result.win_rate == pytest.approx(1.0)
        # Equal-weight taxonomy leaves no per-category breakdown.
        assert not hasattr(result, "pnl_by_category")

    def test_single_wallet_never_triggers_consensus(self):
        backtester = QuorumBacktester(config=BacktestConfig())

        result = backtester.run([bt_signal("solo", "0xaaa", price=0.40)], {"T1": 0.80})

        assert result.total_signals == 1
        assert result.quorum_hits == 0
        assert result.quorum_misses == 1
        assert result.orders_executed == 0
        assert result.win_rate == 0

    def test_vwap_entry_drives_pnl_not_first_vote_price(self):
        # Entry must be the size-weighted 0.45, not the first wallet's 0.40;
        # this pins the weighting end to end through the default P&L model.
        backtester = QuorumBacktester()

        result = backtester.run(two_wallet_hit_signals(), {"T1": 0.55})

        expected = 100.0 * (0.55 - 0.45) / 0.45
        assert result.total_pnl_usd == pytest.approx(expected)

    def test_custom_pnl_fn_receives_consensus_and_exit(self):
        seen = {}

        def pnl_fn(consensus, exit_price):
            seen["vwap"] = consensus.vwap_price
            seen["exit"] = exit_price
            return 5.0

        backtester = QuorumBacktester()

        result = backtester.run(two_wallet_hit_signals(), {"T1": 0.80}, get_pnl_fn=pnl_fn)

        assert seen["vwap"] == pytest.approx(0.45)
        assert seen["exit"] == pytest.approx(0.80)
        assert result.total_pnl_usd == pytest.approx(5.0)

    def test_votes_outside_window_do_not_combine(self):
        signals = [
            bt_signal("s1", "0xaaa", price=0.40),
            bt_signal("s2", "0xbbb", price=0.40, offset_seconds=620.0),
        ]
        backtester = QuorumBacktester()

        result = backtester.run(signals, {"T1": 0.80})

        assert result.quorum_hits == 0
        assert result.quorum_misses == 2


class TestSweepAndSynthetic:
    """Synthetic data generation and parameter sweeps stay category-free."""

    def test_synthetic_signals_carry_sizes_only(self):
        signals = generate_synthetic_signals(num_signals=20, num_wallets=4, num_tokens=5)

        assert len(signals) == 20
        assert all(s.size_usd > 0 for s in signals)
        assert all(not hasattr(s, "wallet_category") for s in signals)

    def test_sweep_returns_sharpe_ranked_results(self):
        backtester = QuorumBacktester()

        results = backtester.run_parameter_sweep(
            two_wallet_hit_signals(),
            {"T1": 0.80},
            param_grid={
                "min_quorum_count": [2, 3],
                "max_acceptable_price": [0.80],
            },
        )

        assert len(results) == 2
        sharpes = [r.sharpe_ratio for r in results]
        assert sharpes == sorted(sharpes, reverse=True)
        # Only the min_quorum_count=2 combination can execute an order.
        executed = [r for r in results if r.orders_executed == 1]
        assert len(executed) == 1
        assert executed[0].config.min_quorum_count == 2
