"""Tests for Kelly sizing."""

import pytest

from weather_copy_bot.sizing import (
    KellyCalculator,
    KellyConfig,
    kelly_fraction,
)


class TestKellyCalculator:
    """Tests for KellyCalculator."""

    def test_positive_edge(self):
        """Test with positive expected value."""
        calc = KellyCalculator()

        result = calc.calculate(
            win_rate=0.55,
            avg_win=100.0,
            avg_loss=90.0,
            max_position=250.0,
        )

        assert result.kelly_fraction > 0
        assert result.adjusted_size > 0
        assert result.reason == "kelly"

    def test_negative_edge(self):
        """Test with negative expected value."""
        calc = KellyCalculator()

        result = calc.calculate(
            win_rate=0.40,
            avg_win=100.0,
            avg_loss=90.0,
            max_position=250.0,
        )

        assert result.kelly_fraction == 0
        assert result.adjusted_size == 0

    def test_half_kelly(self):
        """Test that half-Kelly reduces size."""
        calc_full = KellyCalculator(KellyConfig(use_half_kelly=False))
        calc_half = KellyCalculator(KellyConfig(use_half_kelly=True))

        result_full = calc_full.calculate(win_rate=0.55, avg_win=100.0, avg_loss=90.0)
        result_half = calc_half.calculate(win_rate=0.55, avg_win=100.0, avg_loss=90.0)

        assert result_half.kelly_fraction < result_full.kelly_fraction

    def test_max_kelly_limit(self):
        """Test that max Kelly fraction is enforced."""
        config = KellyConfig(max_kelly_fraction=0.10)
        calc = KellyCalculator(config)

        result = calc.calculate(
            win_rate=0.70,
            avg_win=200.0,
            avg_loss=100.0,
            max_position=250.0,
        )

        assert result.kelly_fraction <= 0.10

    def test_invalid_win_rate(self):
        """Test handling of invalid win rate."""
        calc = KellyCalculator()

        # Win rate of 0
        result = calc.calculate(win_rate=0.0, avg_win=100.0, avg_loss=90.0)
        assert result.reason == "invalid_win_rate"

        # Win rate of 1
        result = calc.calculate(win_rate=1.0, avg_win=100.0, avg_loss=90.0)
        assert result.reason == "invalid_win_rate"

    def test_expected_value_calculation(self):
        """Test expected value is calculated correctly."""
        calc = KellyCalculator()

        result = calc.calculate(
            win_rate=0.60,
            avg_win=50.0,
            avg_loss=50.0,
        )

        # EV = 0.6 * 50 - 0.4 * 50 = 30 - 20 = 10
        assert result.expected_value == 10.0


class TestKellyFraction:
    """Tests for simple kelly_fraction function."""

    def test_simple_calculation(self):
        """Test basic Kelly calculation."""
        # f* = (bp - q) / b
        # b = 100/100 = 1
        # p = 0.6
        # q = 0.4
        # f* = (1 * 0.6 - 0.4) / 1 = 0.2
        fraction = kelly_fraction(win_rate=0.6, avg_win=100.0, avg_loss=100.0)
        assert fraction == pytest.approx(0.2, rel=0.01)

    def test_zero_fraction(self):
        """Test when Kelly is negative or zero."""
        # p < 1/b means negative edge
        fraction = kelly_fraction(win_rate=0.3, avg_win=100.0, avg_loss=100.0)
        assert fraction == 0.0

    def test_clamped_fraction(self):
        """Test that fraction is clamped to 0.25 max."""
        fraction = kelly_fraction(win_rate=0.9, avg_win=500.0, avg_loss=100.0)
        # Raw Kelly would be high, should be clamped
        assert fraction <= 0.25
