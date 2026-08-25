"""Liquidity-aware Kelly Criterion sizing for Polymarket positions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiquidityParams:
    """Liquidity parameters for a market."""

    spread: float
    market_depth: float
    avg_daily_volume: float
    slippage_coefficient: float = 0.001


@dataclass
class KellyParams:
    """Kelly criterion parameters."""

    kelly_fraction: float = 0.25
    max_position_size: float = 1000.0
    min_position_size: float = 1.0
    risk_free_rate: float = 0.0


@dataclass
class PositionSizingResult:
    """Result of position sizing calculation."""

    position_size: float
    expected_value: float
    kelly_fraction: float
    adjusted_for_liquidity: bool
    liquidity_discount: float


class LiquidityAwareKellySizer:
    """Liquidity-aware Kelly Criterion position sizer."""

    def __init__(
        self,
        kelly_params: KellyParams | None = None,
        liquidity_params: LiquidityParams | None = None,
    ) -> None:
        self.kelly_params = kelly_params or KellyParams()
        self.liquidity_params = liquidity_params

    def calculate_position_size(
        self,
        probability: float,
        odds: float,
        bankroll: float,
        liquidity: LiquidityParams | None = None,
    ) -> PositionSizingResult:
        """Calculate optimal position size with liquidity adjustments."""
        liq_params = liquidity or self.liquidity_params
        kelly = self.kelly_params

        base_kelly = self._calculate_kelly(probability, odds)
        adjusted_kelly = base_kelly * kelly.kelly_fraction

        liquidity_discount = 1.0
        if liq_params:
            liquidity_discount = self._calculate_liquidity_discount(
                adjusted_kelly, liq_params, bankroll
            )
            adjusted_kelly *= liquidity_discount

        position_size = bankroll * adjusted_kelly
        position_size = max(kelly.min_position_size, min(kelly.max_position_size, position_size))

        expected_value = self._calculate_expected_value(probability, odds, position_size, bankroll)

        return PositionSizingResult(
            position_size=position_size,
            expected_value=expected_value,
            kelly_fraction=adjusted_kelly,
            adjusted_for_liquidity=liq_params is not None,
            liquidity_discount=liquidity_discount,
        )

    def _calculate_kelly(self, probability: float, odds: float) -> float:
        """Calculate raw Kelly fraction."""
        if odds <= 0 or probability <= 0 or probability >= 1:
            return 0.0

        b = odds - 1
        q = 1 - probability
        p = probability

        kelly = (b * p - q) / b
        return max(0.0, min(1.0, kelly))

    def _calculate_liquidity_discount(
        self, kelly_fraction: float, liquidity: LiquidityParams, bankroll: float
    ) -> float:
        """Calculate liquidity-based discount factor."""
        proposed_position = bankroll * kelly_fraction

        if proposed_position <= 0:
            return 1.0

        volume_ratio = proposed_position / max(liquidity.avg_daily_volume, 1.0)
        depth_ratio = proposed_position / max(liquidity.market_depth, 1.0)

        volume_penalty = max(0.1, 1.0 - volume_ratio * liquidity.slippage_coefficient)
        depth_penalty = max(0.1, 1.0 - depth_ratio * 0.1)
        spread_penalty = max(0.1, 1.0 - liquidity.spread * 10)

        discount = volume_penalty * depth_penalty * spread_penalty
        return max(0.1, min(1.0, discount))

    def _calculate_expected_value(
        self, probability: float, odds: float, position_size: float, bankroll: float
    ) -> float:
        """Calculate expected value of position."""
        if bankroll <= 0 or position_size <= 0:
            return 0.0

        b = odds - 1
        p = probability
        q = 1 - probability

        win_amount = position_size * b
        lose_amount = position_size

        expected_return = p * win_amount - q * lose_amount
        return expected_return / bankroll

    def estimate_slippage(
        self, position_size: float, liquidity: LiquidityParams
    ) -> float:
        """Estimate slippage for a given position size."""
        volume_ratio = position_size / max(liquidity.avg_daily_volume, 1.0)
        depth_ratio = position_size / max(liquidity.market_depth, 1.0)

        slippage = (
            liquidity.spread / 2 +
            volume_ratio * liquidity.slippage_coefficient +
            depth_ratio * 0.05
        )
        return min(0.5, slippage)

    def get_max_affordable_position(
        self, bankroll: float, liquidity: LiquidityParams, max_slippage: float = 0.02
    ) -> float:
        """Calculate maximum position size for given slippage tolerance."""
        low = self.kelly_params.min_position_size
        high = min(bankroll, liquidity.market_depth * 0.1)

        for _ in range(20):
            mid = (low + high) / 2
            slippage = self.estimate_slippage(mid, liquidity)

            if slippage < max_slippage:
                low = mid
            else:
                high = mid

        return low
