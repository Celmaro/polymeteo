"""Kelly Criterion and position sizing calculators with Logit-Space support."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class KellyConfig:
    """Configuration for Kelly sizing."""

    # Kelly fraction limits
    max_kelly_fraction: float = 0.25  # Never risk more than 25% of bankroll
    use_half_kelly: bool = True  # Half-Kelly for risk reduction
    min_kelly_fraction: float = 0.01  # Minimum 1% even if Kelly says less

    # Edge buffer
    edge_buffer_bps: float = 0.0  # Add buffer to required edge
    kelly_scaling: float = 1.0  # Global Kelly multiplier (0.5 = half Kelly)

    # Logit-space configuration
    use_logit_space: bool = True  # Use logit-space for probability modeling
    logit_clip_range: Tuple[float, float] = (0.01, 0.99)  # Clip probabilities


@dataclass
class SizingResult:
    """Result of position sizing calculation."""

    base_size: float
    kelly_fraction: float
    adjusted_size: float
    edge_required: float
    expected_value: float
    reason: str
    # Logit-space metrics
    logit_price: Optional[float] = None
    logit_edge: Optional[float] = None
    logit_probability: Optional[float] = None


@dataclass
class LogitMetrics:
    """Logit-space probability metrics."""

    price: float
    logit: float
    probability: float
    implied_probability: float
    edge_logit: float
    edge_probability: float
    is_stable: bool  # True if probability is in stable range [0.1, 0.9]


class LogitKellyCalculator:
    """
    Kelly Criterion calculator using logit-space probability modeling.
    
    Logit-space modeling provides numerical stability for:
    - Binary prediction tokens (0 <= p <= 1)
    - High/low probability weather bands
    - Tail-risk scenarios
    
    Formulas:
        logit(p) = ln(p / (1 - p))
        probability = 1 / (1 + exp(-logit))
        logit_space_kelly = (p * b - q) / b  (in logit space)
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()

    def _price_to_logit(self, price: float) -> float:
        """
        Convert price to logit space.
        
        For Polymarket binary tokens:
        - Price directly represents implied probability
        - logit(price) gives stable representation for edge calculation
        """
        # Clip to avoid log(0) or log(negative)
        p = max(self.config.logit_clip_range[0], 
                min(price, self.config.logit_clip_range[1]))
        return math.log(p / (1 - p))

    def _logit_to_probability(self, logit: float) -> float:
        """Convert logit back to probability."""
        return 1 / (1 + math.exp(-logit))

    def calculate_logit_metrics(
        self,
        market_price: float,
        estimated_true_prob: float,
    ) -> LogitMetrics:
        """
        Calculate logit-space metrics for probability comparison.
        
        Args:
            market_price: Current market price (implied probability)
            estimated_true_prob: Estimated true probability (e.g., from oracle)
            
        Returns:
            LogitMetrics with all calculations
        """
        logit_market = self._price_to_logit(market_price)
        logit_true = self._price_to_logit(estimated_true_prob)
        
        # Edge in logit space (stable for near-boundary probabilities)
        logit_edge = logit_true - logit_market
        
        # Convert back to probability space for interpretability
        edge_probability = self._logit_to_probability(logit_market + logit_edge)
        
        # Stability check: probability in [0.1, 0.9] is numerically stable
        is_stable = 0.1 <= market_price <= 0.9
        
        return LogitMetrics(
            price=market_price,
            logit=logit_market,
            probability=market_price,
            implied_probability=estimated_true_prob,
            edge_logit=logit_edge,
            edge_probability=edge_probability - market_price,
            is_stable=is_stable,
        )

    def calculate_logit_kelly(
        self,
        market_price: float,
        estimated_true_prob: float,
        avg_win: float,
        avg_loss: float,
    ) -> SizingResult:
        """
        Calculate Kelly sizing using logit-space probability modeling.
        
        This method is more stable for:
        - Low probability events (e.g., rare weather: hurricane, blizzard)
        - High probability events (e.g., common: temperature > 0°C)
        - Edge cases near boundaries (p -> 0 or p -> 1)
        
        Args:
            market_price: Current market price
            estimated_true_prob: Estimated true probability
            avg_win: Average winning amount
            avg_loss: Average losing amount
            
        Returns:
            SizingResult with Kelly calculations
        """
        # Get logit metrics
        metrics = self.calculate_logit_metrics(market_price, estimated_true_prob)
        
        # Use estimated true probability for Kelly calculation
        # This is more robust than using win rate directly
        p = estimated_true_prob
        q = 1 - p
        
        # Calculate Kelly in probability space first
        b = avg_win / avg_loss if avg_loss > 0 else 1.0
        kelly_raw = (b * p - q) / b
        
        # Check if edge exists (true prob > market prob)
        if metrics.edge_probability <= 0:
            return SizingResult(
                base_size=0.0,
                kelly_fraction=0.0,
                adjusted_size=0.0,
                edge_required=0.0,
                expected_value=0.0,
                reason="no_edge",
                logit_price=metrics.logit,
                logit_edge=metrics.edge_logit,
                logit_probability=p,
            )
        
        # Apply constraints
        kelly_scaled = kelly_raw * self.config.kelly_scaling
        kelly_fraction = max(0, min(kelly_scaled, self.config.max_kelly_fraction))
        
        # Apply Half-Kelly if enabled
        if self.config.use_half_kelly:
            kelly_fraction = kelly_fraction / 2
        
        kelly_fraction = max(kelly_fraction, self.config.min_kelly_fraction)
        
        # Calculate expected value
        expected_value = p * avg_win - q * avg_loss
        
        return SizingResult(
            base_size=kelly_fraction * 10000,  # Assuming $10k bankroll
            kelly_fraction=round(kelly_fraction, 4),
            adjusted_size=round(kelly_fraction * 10000, 2),
            edge_required=round(metrics.edge_probability, 4),
            expected_value=round(expected_value, 2),
            reason="logit_kelly",
            logit_price=round(metrics.logit, 4),
            logit_edge=round(metrics.edge_logit, 4),
            logit_probability=round(p, 4),
        )

    def calculate_with_bankroll(
        self,
        market_price: float,
        estimated_true_prob: float,
        avg_win: float,
        avg_loss: float,
        bankroll: float,
        max_position_pct: float = 0.02,  # Max 2% of bankroll per trade
    ) -> SizingResult:
        """
        Calculate Kelly sizing with explicit bankroll management.
        
        Args:
            market_price: Current market price
            estimated_true_prob: Estimated true probability
            avg_win: Average winning amount
            avg_loss: Average losing amount
            bankroll: Total bankroll in USD
            max_position_pct: Maximum position as % of bankroll
            
        Returns:
            SizingResult with bankroll-adjusted sizing
        """
        # Calculate raw Kelly
        result = self.calculate_logit_kelly(
            market_price, estimated_true_prob, avg_win, avg_loss
        )
        
        if result.kelly_fraction == 0:
            return result
        
        # Calculate max position based on bankroll
        max_position = bankroll * max_position_pct
        
        # Adjust size
        adjusted_size = min(result.kelly_fraction * bankroll, max_position)
        
        return SizingResult(
            base_size=result.base_size,
            kelly_fraction=result.kelly_fraction,
            adjusted_size=round(adjusted_size, 2),
            edge_required=result.edge_required,
            expected_value=result.expected_value,
            reason=result.reason,
            logit_price=result.logit_price,
            logit_edge=result.logit_edge,
            logit_probability=result.logit_probability,
        )


class KellyCalculator:
    """
    Kelly Criterion calculator for position sizing.
    
    Kelly Criterion: f* = (bp - q) / b
    
    Where:
        b = odds received on the wager (profit / loss)
        p = probability of winning
        q = probability of losing = 1 - p
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()
        self._logit_calc = LogitKellyCalculator(config)

    def calculate(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        max_position: float = 250.0,
        min_position: float = 5.0,
    ) -> SizingResult:
        """Standard Kelly calculation."""
        # Validate inputs
        if win_rate <= 0 or win_rate >= 1:
            return SizingResult(
                base_size=0.0,
                kelly_fraction=0.0,
                adjusted_size=0.0,
                edge_required=0.0,
                expected_value=0.0,
                reason="invalid_win_rate",
            )

        if avg_loss <= 0:
            return SizingResult(
                base_size=0.0,
                kelly_fraction=0.0,
                adjusted_size=0.0,
                edge_required=0.0,
                expected_value=0.0,
                reason="invalid_avg_loss",
            )

        # Calculate Kelly fraction
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p

        kelly_raw = (b * p - q) / b
        kelly_scaled = kelly_raw * self.config.kelly_scaling
        kelly_fraction = max(0, min(kelly_scaled, self.config.max_kelly_fraction))
        kelly_fraction = max(kelly_fraction, self.config.min_kelly_fraction)

        if self.config.use_half_kelly:
            kelly_fraction = kelly_fraction / 2

        base_size = kelly_fraction * max_position
        adjusted_size = max(min_position, min(base_size, max_position))
        expected_value = (p * avg_win) - (q * avg_loss)
        edge_required = (q * avg_loss) / (avg_win + avg_loss)

        return SizingResult(
            base_size=round(base_size, 2),
            kelly_fraction=round(kelly_fraction, 4),
            adjusted_size=round(adjusted_size, 2),
            edge_required=round(edge_required, 4),
            expected_value=round(expected_value, 2),
            reason="kelly" if kelly_fraction > 0 else "kelly_zero",
        )

    def calculate_with_logit(
        self,
        market_price: float,
        estimated_true_prob: float,
        avg_win: float,
        avg_loss: float,
        bankroll: float = 10000.0,
    ) -> SizingResult:
        """
        Calculate Kelly using logit-space for better stability.
        
        Use this for:
        - Low probability events (< 10%)
        - High probability events (> 90%)
        - Weather tail-risks
        """
        return self._logit_calc.calculate_with_bankroll(
            market_price=market_price,
            estimated_true_prob=estimated_true_prob,
            avg_win=avg_win,
            avg_loss=avg_loss,
            bankroll=bankroll,
        )


class DynamicKellyCalculator:
    """Dynamic Kelly calculator with EMA-based adaptation."""

    def __init__(
        self,
        lookback_trades: int = 100,
        ema_alpha: float = 0.1,
        config: Optional[KellyConfig] = None,
    ):
        self.lookback = lookback_trades
        self.ema_alpha = ema_alpha
        self.config = config or KellyConfig()
        self._base_calc = KellyCalculator(config)
        self._logit_calc = LogitKellyCalculator(config)
        
        self._ema_win_rate: Optional[float] = None
        self._ema_avg_win: Optional[float] = None
        self._ema_avg_loss: Optional[float] = None
        self._trade_count = 0

    def update(self, won: bool, pnl: float) -> None:
        """Update EMA state with new trade result."""
        self._trade_count += 1
        
        if self._ema_win_rate is None:
            self._ema_win_rate = 1.0 if won else 0.0
            self._ema_avg_win = max(0, pnl) if won else 0.0
            self._ema_avg_loss = max(0, -pnl) if not won else 0.0
        else:
            self._ema_win_rate = (
                self.ema_alpha * (1.0 if won else 0.0) +
                (1 - self.ema_alpha) * self._ema_win_rate
            )
            
            if won:
                self._ema_avg_win = (
                    self.ema_alpha * max(0, pnl) +
                    (1 - self.ema_alpha) * (self._ema_avg_win or max(0, pnl))
                )
            else:
                self._ema_avg_loss = (
                    self.ema_alpha * max(0, -pnl) +
                    (1 - self.ema_alpha) * (self._ema_avg_loss or max(0, -pnl))
                )

    def calculate(self, max_position: float = 250.0, min_position: float = 5.0) -> SizingResult:
        """Calculate position size using dynamic EMA values."""
        if self._trade_count < 10:
            return SizingResult(
                base_size=min_position,
                kelly_fraction=0.05,
                adjusted_size=min_position,
                edge_required=0.5,
                expected_value=0.0,
                reason="insufficient_data",
            )

        return self._base_calc.calculate(
            win_rate=self._ema_win_rate or 0.5,
            avg_win=self._ema_avg_win or 10.0,
            avg_loss=self._ema_avg_loss or 10.0,
            max_position=max_position,
            min_position=min_position,
        )

    @property
    def stats(self) -> dict:
        """Get current EMA statistics."""
        return {
            "trade_count": self._trade_count,
            "ema_win_rate": self._ema_win_rate,
            "ema_avg_win": self._ema_avg_win,
            "ema_avg_loss": self._ema_avg_loss,
        }


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Simple Kelly fraction calculation."""
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    
    b = avg_win / avg_loss
    p = win_rate
    q = 1 - p
    
    kelly = (b * p - q) / b
    return max(0, min(kelly, 0.25))


def logit_kelly_fraction(
    market_price: float,
    estimated_prob: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """
    Calculate Kelly fraction in logit space.
    
    More stable for near-boundary probabilities.
    """
    calc = LogitKellyCalculator()
    result = calc.calculate_logit_kelly(
        market_price=market_price,
        estimated_true_prob=estimated_prob,
        avg_win=avg_win,
        avg_loss=avg_loss,
    )
    return result.kelly_fraction
