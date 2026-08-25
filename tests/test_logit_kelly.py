"""Tests for Logit Kelly Calculator."""

import pytest

from weather_copy_bot.sizing.kelly import (
    KellyCalculator,
    LogitKellyCalculator,
    LogitMetrics,
)


class TestLogitKellyCalculator:
    """Tests for LogitKellyCalculator."""

    def test_price_to_logit(self):
        """Test price to logit conversion."""
        calc = LogitKellyCalculator()

        # p = 0.5 -> logit(0.5) = 0
        logit_50 = calc._price_to_logit(0.5)
        assert abs(logit_50) < 0.01

        # p = 0.7 -> logit > 0
        logit_70 = calc._price_to_logit(0.7)
        assert logit_70 > 0

        # p = 0.3 -> logit < 0
        logit_30 = calc._price_to_logit(0.3)
        assert logit_30 < 0

    def test_logit_to_probability(self):
        """Test logit to probability conversion."""
        calc = LogitKellyCalculator()

        # logit(0) -> 0.5
        prob_50 = calc._logit_to_probability(0)
        assert abs(prob_50 - 0.5) < 0.01

        # Round trip: price -> logit -> price
        original = 0.75
        logit = calc._price_to_logit(original)
        back = calc._logit_to_probability(logit)
        assert abs(back - original) < 0.01

    def test_calculate_logit_metrics(self):
        """Test logit metrics calculation."""
        calc = LogitKellyCalculator()

        # Market at 0.5, true prob at 0.6
        metrics = calc.calculate_logit_metrics(
            market_price=0.5,
            estimated_true_prob=0.6,
        )

        assert metrics.price == 0.5
        assert metrics.edge_probability == pytest.approx(0.1, abs=0.01)
        assert metrics.is_stable is True

    def test_edge_detection_no_edge(self):
        """Test detection when no edge exists."""
        calc = LogitKellyCalculator()

        # Market at 0.7, true prob at 0.5 (no edge)
        result = calc.calculate_logit_kelly(
            market_price=0.7,
            estimated_true_prob=0.5,
            avg_win=30.0,
            avg_loss=70.0,
        )

        assert result.reason == "no_edge"
        assert result.kelly_fraction == 0.0

    def test_edge_detection_with_edge(self):
        """Test detection when edge exists."""
        calc = LogitKellyCalculator()

        # Market at 0.5, true prob at 0.6 (10% edge)
        result = calc.calculate_logit_kelly(
            market_price=0.5,
            estimated_true_prob=0.6,
            avg_win=40.0,
            avg_loss=60.0,
        )

        assert result.reason == "logit_kelly"
        assert result.kelly_fraction > 0

    def test_boundary_probabilities(self):
        """Test with near-boundary probabilities."""
        calc = LogitKellyCalculator()

        # Low probability (rare event)
        result = calc.calculate_logit_kelly(
            market_price=0.05,
            estimated_true_prob=0.15,
            avg_win=85.0,
            avg_loss=15.0,
        )

        # Should not crash and should handle edge case
        assert result is not None
        assert result.logit_price is not None

    def test_high_probability(self):
        """Test with high probability."""
        calc = LogitKellyCalculator()

        # High probability (likely event)
        result = calc.calculate_logit_kelly(
            market_price=0.85,
            estimated_true_prob=0.92,
            avg_win=8.0,
            avg_loss=92.0,
        )

        assert result is not None

    def test_calculate_with_bankroll(self):
        """Test bankroll-based sizing."""
        calc = LogitKellyCalculator()

        result = calc.calculate_with_bankroll(
            market_price=0.5,
            estimated_true_prob=0.65,
            avg_win=35.0,
            avg_loss=65.0,
            bankroll=10000.0,
            max_position_pct=0.02,
        )

        assert result.adjusted_size <= 200.0  # 2% of $10k

    def test_stability_check(self):
        """Test stability check for boundary probabilities."""
        calc = LogitKellyCalculator()

        # Unstable: very low probability
        metrics = calc.calculate_logit_metrics(0.01, 0.05)
        assert metrics.is_stable is False

        # Stable: mid-range probability
        metrics = calc.calculate_logit_metrics(0.5, 0.6)
        assert metrics.is_stable is True


class TestKellyCalculator:
    """Tests for KellyCalculator with logit integration."""

    def test_standard_kelly(self):
        """Test standard Kelly calculation."""
        calc = KellyCalculator()

        result = calc.calculate(
            win_rate=0.55,
            avg_win=55.0,
            avg_loss=45.0,
        )

        assert result.kelly_fraction > 0
        assert result.reason == "kelly"

    def test_calculate_with_logit(self):
        """Test logit-enhanced Kelly."""
        calc = KellyCalculator()

        result = calc.calculate_with_logit(
            market_price=0.5,
            estimated_true_prob=0.65,
            avg_win=35.0,
            avg_loss=65.0,
            bankroll=10000.0,
        )

        assert result.logit_price is not None
        assert result.logit_edge is not None


class TestLogitMetrics:
    """Tests for LogitMetrics."""

    def test_metrics_creation(self):
        """Test LogitMetrics creation."""
        metrics = LogitMetrics(
            price=0.5,
            logit=0.0,
            probability=0.5,
            implied_probability=0.6,
            edge_logit=0.4,
            edge_probability=0.1,
            is_stable=True,
        )

        assert metrics.price == 0.5
        assert metrics.is_stable is True


class TestEdgeCases:
    """Tests for edge cases."""

    def test_zero_avg_loss(self):
        """Test handling of zero avg loss."""
        calc = LogitKellyCalculator()

        result = calc.calculate_logit_kelly(
            market_price=0.5,
            estimated_true_prob=0.6,
            avg_win=40.0,
            avg_loss=0.0,  # Invalid
        )

        assert result.kelly_fraction == 0.0

    def test_very_small_probability(self):
        """Test very small probability (near 0)."""
        calc = LogitKellyCalculator()

        result = calc.calculate_logit_kelly(
            market_price=0.001,
            estimated_true_prob=0.01,
            avg_win=99.0,
            avg_loss=1.0,
        )

        # Should handle gracefully without crashing
        assert result is not None

    def test_very_large_probability(self):
        """Test very large probability (near 1)."""
        calc = LogitKellyCalculator()

        result = calc.calculate_logit_kelly(
            market_price=0.999,
            estimated_true_prob=0.995,
            avg_win=0.5,
            avg_loss=99.5,
        )

        # Should handle gracefully without crashing
        assert result is not None
