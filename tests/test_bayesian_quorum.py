"""Tests for Bayesian quorum engine."""
from __future__ import annotations

import pytest

from weather_copy_bot.bayesian_quorum import (
    BayesianQuorumEngine,
    ConsensusResult,
    ProbabilityEstimate,
    WalletType,
    WalletWeight,
)


class TestWalletType:
    """Test WalletType enum."""

    def test_wallet_type_has_smart_bot(self):
        """WalletType should have SMART_BOT value."""
        assert WalletType.SMART_BOT.value == "smart_bot"

    def test_wallet_type_has_smart_trader(self):
        """WalletType should have SMART_TRADER value."""
        assert WalletType.SMART_TRADER.value == "smart_trader"

    def test_wallet_type_has_whale(self):
        """WalletType should have WHALE value."""
        assert WalletType.WHALE.value == "whale"

    def test_wallet_type_has_regular(self):
        """WalletType should have REGULAR value."""
        assert WalletType.REGULAR.value == "regular"


class TestWalletWeight:
    """Test WalletWeight dataclass."""

    def test_weight_has_wallet_type(self):
        """Weight should have wallet_type field."""
        weight = WalletWeight(wallet_type=WalletType.SMART_BOT, weight=1.5)
        assert weight.wallet_type == WalletType.SMART_BOT

    def test_weight_has_weight_value(self):
        """Weight should have weight value."""
        weight = WalletWeight(wallet_type=WalletType.SMART_BOT, weight=1.5)
        assert weight.weight == 1.5

    def test_weight_defaults(self):
        """Weight should have default weight of 1.0."""
        weight = WalletWeight(wallet_type=WalletType.REGULAR)
        assert weight.weight == 1.0


class TestProbabilityEstimate:
    """Test ProbabilityEstimate dataclass."""

    def test_estimate_has_probability(self):
        """Estimate should have probability field."""
        estimate = ProbabilityEstimate(
            probability=0.65,
            confidence=0.8,
            wallet_type=WalletType.SMART_TRADER,
        )
        assert estimate.probability == 0.65

    def test_estimate_has_confidence(self):
        """Estimate should have confidence field."""
        estimate = ProbabilityEstimate(
            probability=0.65,
            confidence=0.8,
            wallet_type=WalletType.SMART_TRADER,
        )
        assert estimate.confidence == 0.8

    def test_estimate_has_wallet_type(self):
        """Estimate should have wallet_type field."""
        estimate = ProbabilityEstimate(
            probability=0.65,
            confidence=0.8,
            wallet_type=WalletType.SMART_TRADER,
        )
        assert estimate.wallet_type == WalletType.SMART_TRADER


class TestBayesianQuorumEngine:
    """Test BayesianQuorumEngine class."""

    def test_engine_initializes(self):
        """Engine should initialize without errors."""
        engine = BayesianQuorumEngine()
        assert engine is not None

    def test_engine_has_default_weights(self):
        """Engine should have default wallet weights."""
        engine = BayesianQuorumEngine()
        assert engine.smart_bot_weight == 1.5
        assert engine.smart_trader_weight == 1.2
        assert engine.whale_weight == 0.8
        assert engine.regular_weight == 1.0

    def test_engine_has_aggregate_method(self):
        """Engine should have aggregate_probabilities method."""
        engine = BayesianQuorumEngine()
        assert hasattr(engine, "aggregate_probabilities")

    def test_engine_has_update_belief_method(self):
        """Engine should have update_belief method."""
        engine = BayesianQuorumEngine()
        assert hasattr(engine, "update_belief")

    def test_engine_has_get_consensus_method(self):
        """Engine should have get_consensus method."""
        engine = BayesianQuorumEngine()
        assert hasattr(engine, "get_consensus")

    def test_engine_has_prior(self):
        """Engine should have prior probability."""
        engine = BayesianQuorumEngine()
        assert engine._prior == 0.5


class TestBayesianQuorumEngineAsync:
    """Test BayesianQuorumEngine async methods."""

    @pytest.mark.asyncio
    async def test_aggregate_empty_estimates(self):
        """Aggregate with no estimates returns prior."""
        engine = BayesianQuorumEngine()
        result = await engine.aggregate_probabilities([])
        assert result == 0.5

    @pytest.mark.asyncio
    async def test_aggregate_single_estimate(self):
        """Aggregate with single estimate."""
        engine = BayesianQuorumEngine()
        estimate = ProbabilityEstimate(probability=0.7, confidence=1.0)
        result = await engine.aggregate_probabilities([estimate])
        assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_aggregate_multiple_estimates(self):
        """Aggregate multiple estimates."""
        engine = BayesianQuorumEngine()
        estimates = [
            ProbabilityEstimate(probability=0.6, confidence=0.8, wallet_type=WalletType.SMART_BOT),
            ProbabilityEstimate(probability=0.7, confidence=0.9, wallet_type=WalletType.SMART_TRADER),
        ]
        result = await engine.aggregate_probabilities(estimates)
        assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_update_belief(self):
        """Update belief with evidence."""
        engine = BayesianQuorumEngine()
        estimate = ProbabilityEstimate(probability=0.8, confidence=0.5, wallet_type=WalletType.WHALE)
        result = await engine.update_belief(0.5, estimate)
        assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_get_consensus_empty(self):
        """Get consensus with no estimates."""
        engine = BayesianQuorumEngine()
        result = await engine.get_consensus([])
        assert result.consensus_probability == 0.5
        assert result.confidence == 0.0
        assert result.num_sources == 0

    @pytest.mark.asyncio
    async def test_get_consensus_with_estimates(self):
        """Get consensus with estimates."""
        engine = BayesianQuorumEngine()
        estimates = [
            ProbabilityEstimate(probability=0.6, confidence=1.0, wallet_type=WalletType.SMART_BOT),
            ProbabilityEstimate(probability=0.65, confidence=1.0, wallet_type=WalletType.REGULAR),
        ]
        result = await engine.get_consensus(estimates)
        assert 0.0 <= result.consensus_probability <= 1.0
        assert result.num_sources == 2
        assert result.weighted_sources >= 2


class TestConsensusResult:
    """Test ConsensusResult dataclass."""

    def test_consensus_result_fields(self):
        """ConsensusResult should have all fields."""
        result = ConsensusResult(
            consensus_probability=0.65,
            confidence=0.8,
            num_sources=3,
            weighted_sources=4,
        )
        assert result.consensus_probability == 0.65
        assert result.confidence == 0.8
        assert result.num_sources == 3
        assert result.weighted_sources == 4
