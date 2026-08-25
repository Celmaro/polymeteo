"""Bayesian quorum engine for probability aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WalletType(Enum):
    """Wallet classification types."""

    SMART_BOT = "smart_bot"
    SMART_TRADER = "smart_trader"
    WHALE = "whale"
    REGULAR = "regular"


@dataclass
class WalletWeight:
    """Weight assigned to a wallet type."""

    wallet_type: WalletType
    weight: float = 1.0


@dataclass
class ProbabilityEstimate:
    """Probability estimate from a source."""

    probability: float
    confidence: float = 1.0
    wallet_type: WalletType = WalletType.REGULAR


@dataclass
class ConsensusResult:
    """Result of consensus aggregation."""

    consensus_probability: float
    confidence: float
    num_sources: int
    weighted_sources: int


class BayesianQuorumEngine:
    """Bayesian probability aggregation engine for Polymarket markets."""

    def __init__(
        self,
        smart_bot_weight: float = 1.5,
        smart_trader_weight: float = 1.2,
        whale_weight: float = 0.8,
        regular_weight: float = 1.0,
    ) -> None:
        self.smart_bot_weight = smart_bot_weight
        self.smart_trader_weight = smart_trader_weight
        self.whale_weight = whale_weight
        self.regular_weight = regular_weight
        self._prior = 0.5

    def get_weight_for_type(self, wallet_type: WalletType) -> float:
        """Get weight for a wallet type."""
        weights = {
            WalletType.SMART_BOT: self.smart_bot_weight,
            WalletType.SMART_TRADER: self.smart_trader_weight,
            WalletType.WHALE: self.whale_weight,
            WalletType.REGULAR: self.regular_weight,
        }
        return weights.get(wallet_type, 1.0)

    async def aggregate_probabilities(
        self, estimates: list[ProbabilityEstimate]
    ) -> float:
        """Aggregate multiple probability estimates using weighted Bayesian update."""
        if not estimates:
            return self._prior

        log_odds = 0.0
        total_weight = 0.0

        for estimate in estimates:
            weight = self.get_weight_for_type(estimate.wallet_type) * estimate.confidence
            p = max(0.001, min(0.999, estimate.probability))
            odds = p / (1 - p)
            log_odds += weight * (1 if odds >= 1 else -1) * (abs(odds) ** 0.5 if odds > 0 else 0)
            total_weight += weight

        if total_weight == 0:
            return self._prior

        normalized_log_odds = log_odds / total_weight
        exp_odds = abs(normalized_log_odds) ** 2 if normalized_log_odds != 0 else 1
        final_odds = exp_odds if normalized_log_odds >= 0 else 1 / exp_odds

        return final_odds / (1 + final_odds)

    async def update_belief(
        self, prior: float, new_evidence: ProbabilityEstimate
    ) -> float:
        """Update belief with new evidence."""
        weight = self.get_weight_for_type(new_evidence.wallet_type)
        effective_weight = weight * new_evidence.confidence
        return (prior * effective_weight + new_evidence.probability) / (effective_weight + 1)

    async def get_consensus(
        self, estimates: list[ProbabilityEstimate]
    ) -> ConsensusResult:
        """Get consensus result with confidence metrics."""
        consensus_prob = await self.aggregate_probabilities(estimates)
        num_sources = len(estimates)

        if num_sources == 0:
            return ConsensusResult(
                consensus_probability=self._prior,
                confidence=0.0,
                num_sources=0,
                weighted_sources=0,
            )

        total_weight = sum(
            self.get_weight_for_type(e.wallet_type) * e.confidence for e in estimates
        )
        avg_confidence = sum(e.confidence for e in estimates) / num_sources

        return ConsensusResult(
            consensus_probability=consensus_prob,
            confidence=min(1.0, avg_confidence * (total_weight / num_sources)),
            num_sources=num_sources,
            weighted_sources=int(total_weight),
        )
