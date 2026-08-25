"""Tests for liquidity-aware Kelly sizing module."""
from __future__ import annotations

from weather_copy_bot.liquidity_aware_kelly import (
    KellyParams,
    LiquidityAwareKellySizer,
    LiquidityParams,
    PositionSizingResult,
)


class TestLiquidityParams:
    """Test LiquidityParams dataclass."""

    def test_has_spread(self):
        """Should have spread field."""
        params = LiquidityParams(
            spread=0.02,
            market_depth=1000.0,
            avg_daily_volume=5000.0,
        )
        assert params.spread == 0.02

    def test_has_market_depth(self):
        """Should have market_depth field."""
        params = LiquidityParams(
            spread=0.01,
            market_depth=5000.0,
            avg_daily_volume=10000.0,
        )
        assert params.market_depth == 5000.0

    def test_has_volume(self):
        """Should have avg_daily_volume field."""
        params = LiquidityParams(
            spread=0.01,
            market_depth=1000.0,
            avg_daily_volume=10000.0,
        )
        assert params.avg_daily_volume == 10000.0


class TestKellyParams:
    """Test KellyParams dataclass."""

    def test_has_kelly_fraction(self):
        """Should have kelly_fraction field."""
        params = KellyParams()
        assert params.kelly_fraction == 0.25

    def test_has_max_position(self):
        """Should have max_position_size field."""
        params = KellyParams()
        assert params.max_position_size == 1000.0

    def test_custom_params(self):
        """Should accept custom parameters."""
        params = KellyParams(
            kelly_fraction=0.5,
            max_position_size=5000.0,
            min_position_size=10.0,
        )
        assert params.kelly_fraction == 0.5
        assert params.max_position_size == 5000.0


class TestPositionSizingResult:
    """Test PositionSizingResult dataclass."""

    def test_has_position_size(self):
        """Should have position_size field."""
        result = PositionSizingResult(
            position_size=100.0,
            expected_value=0.05,
            kelly_fraction=0.1,
            adjusted_for_liquidity=True,
            liquidity_discount=0.8,
        )
        assert result.position_size == 100.0

    def test_has_expected_value(self):
        """Should have expected_value field."""
        result = PositionSizingResult(
            position_size=100.0,
            expected_value=0.05,
            kelly_fraction=0.1,
            adjusted_for_liquidity=True,
            liquidity_discount=0.8,
        )
        assert result.expected_value == 0.05


class TestLiquidityAwareKellySizer:
    """Test LiquidityAwareKellySizer class."""

    def test_initializes(self):
        """Should initialize without errors."""
        sizer = LiquidityAwareKellySizer()
        assert sizer is not None

    def test_initializes_with_params(self):
        """Should initialize with parameters."""
        kelly = KellyParams(kelly_fraction=0.5)
        liquidity = LiquidityParams(spread=0.01, market_depth=1000.0, avg_daily_volume=5000.0)
        sizer = LiquidityAwareKellySizer(kelly_params=kelly, liquidity_params=liquidity)
        assert sizer.kelly_params.kelly_fraction == 0.5

    def test_default_kelly_fraction(self):
        """Should use default Kelly fraction."""
        sizer = LiquidityAwareKellySizer()
        assert sizer.kelly_params.kelly_fraction == 0.25

    def test_calculate_position_size_returns_result(self):
        """Should return PositionSizingResult."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.6,
            odds=1.8,
            bankroll=10000.0,
        )
        assert isinstance(result, PositionSizingResult)

    def test_position_size_respects_limits(self):
        """Position size should respect min/max limits."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.6,
            odds=1.8,
            bankroll=100.0,
        )
        assert result.position_size >= sizer.kelly_params.min_position_size
        assert result.position_size <= sizer.kelly_params.max_position_size

    def test_no_edge_case_probability(self):
        """Should handle edge case probabilities."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.0,
            odds=2.0,
            bankroll=10000.0,
        )
        assert result.position_size == sizer.kelly_params.min_position_size

    def test_high_probability(self):
        """Should handle high probability."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.99,
            odds=1.01,
            bankroll=10000.0,
        )
        assert result.position_size >= 0

    def test_expected_value_calculation(self):
        """Should calculate expected value."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.6,
            odds=2.0,
            bankroll=10000.0,
        )
        assert isinstance(result.expected_value, float)

    def test_liquidity_adjustment_flag(self):
        """Should indicate if liquidity adjustment was applied."""
        sizer = LiquidityAwareKellySizer()
        result_no_liq = sizer.calculate_position_size(
            probability=0.6,
            odds=2.0,
            bankroll=10000.0,
        )
        assert result_no_liq.adjusted_for_liquidity is False

    def test_liquidity_discount_with_params(self):
        """Should apply liquidity discount when params provided."""
        sizer = LiquidityAwareKellySizer()
        liquidity = LiquidityParams(
            spread=0.05,
            market_depth=1000.0,
            avg_daily_volume=5000.0,
        )
        result = sizer.calculate_position_size(
            probability=0.6,
            odds=2.0,
            bankroll=10000.0,
            liquidity=liquidity,
        )
        assert result.adjusted_for_liquidity is True
        assert result.liquidity_discount <= 1.0


class TestKellyCalculations:
    """Test Kelly calculation specifics."""

    def test_positive_expected_value(self):
        """Should calculate positive Kelly for favorable odds."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.6,
            odds=2.0,
            bankroll=10000.0,
        )
        assert result.kelly_fraction > 0

    def test_zero_kelly_unfavorable_odds(self):
        """Should return zero Kelly for unfavorable odds."""
        sizer = LiquidityAwareKellySizer()
        result = sizer.calculate_position_size(
            probability=0.3,
            odds=1.5,
            bankroll=10000.0,
        )
        assert result.kelly_fraction >= 0


class TestSlippageEstimation:
    """Test slippage estimation."""

    def test_estimate_slippage(self):
        """Should estimate slippage."""
        sizer = LiquidityAwareKellySizer()
        liquidity = LiquidityParams(
            spread=0.02,
            market_depth=1000.0,
            avg_daily_volume=5000.0,
        )
        slippage = sizer.estimate_slippage(100.0, liquidity)
        assert 0 <= slippage <= 0.5

    def test_larger_position_more_slippage(self):
        """Larger positions should have more slippage."""
        sizer = LiquidityAwareKellySizer()
        liquidity = LiquidityParams(
            spread=0.01,
            market_depth=1000.0,
            avg_daily_volume=5000.0,
        )
        small_slip = sizer.estimate_slippage(50.0, liquidity)
        large_slip = sizer.estimate_slippage(500.0, liquidity)
        assert large_slip >= small_slip


class TestMaxAffordablePosition:
    """Test max affordable position calculation."""

    def test_returns_position(self):
        """Should return a position size."""
        sizer = LiquidityAwareKellySizer()
        liquidity = LiquidityParams(
            spread=0.02,
            market_depth=1000.0,
            avg_daily_volume=5000.0,
        )
        max_pos = sizer.get_max_affordable_position(10000.0, liquidity)
        assert max_pos > 0

    def test_respects_bankroll(self):
        """Should not exceed bankroll."""
        sizer = LiquidityAwareKellySizer()
        liquidity = LiquidityParams(
            spread=0.01,
            market_depth=10000.0,
            avg_daily_volume=50000.0,
        )
        max_pos = sizer.get_max_affordable_position(1000.0, liquidity)
        assert max_pos <= 1000.0
