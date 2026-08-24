"""Kelly Criterion and position sizing calculators."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


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


@dataclass
class SizingResult:
    """Result of position sizing calculation."""

    base_size: float
    kelly_fraction: float
    adjusted_size: float
    edge_required: float
    expected_value: float
    reason: str


class KellyCalculator:
    """
    Kelly Criterion calculator for position sizing.
    
    Kelly Criterion: f* = (bp - q) / b
    
    Where:
        b = odds received on the wager (profit / loss)
        p = probability of winning
        q = probability of losing = 1 - p
        
    Example:
        calc = KellyCalculator()
        
        result = calc.calculate(
            win_rate=0.55,
            avg_win=100.0,
            avg_loss=90.0,
            max_position=250.0,
        )
        
        print(f"Kelly fraction: {result.kelly_fraction:.2%}")
        print(f"Optimal size: ${result.adjusted_size:.2f}")
    """

    def __init__(self, config: Optional[KellyConfig] = None):
        self.config = config or KellyConfig()

    def calculate(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        max_position: float = 250.0,
        min_position: float = 5.0,
    ) -> SizingResult:
        """
        Calculate optimal position size using Kelly Criterion.
        
        Args:
            win_rate: Historical win rate (0.0 to 1.0)
            avg_win: Average profit on winning trades
            avg_loss: Average loss on losing trades
            max_position: Maximum position size allowed
            min_position: Minimum position size (below this, don't trade)
            
        Returns:
            SizingResult with calculated sizes and metrics
        """
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
        b = avg_win / avg_loss  # Odds received
        p = win_rate
        q = 1 - p

        # Raw Kelly: f* = (bp - q) / b
        kelly_raw = (b * p - q) / b

        # Apply Kelly scaling
        kelly_scaled = kelly_raw * self.config.kelly_scaling

        # Apply constraints
        kelly_fraction = max(0, min(kelly_scaled, self.config.max_kelly_fraction))
        kelly_fraction = max(kelly_fraction, self.config.min_kelly_fraction)

        # Apply Half-Kelly if enabled
        if self.config.use_half_kelly:
            kelly_fraction = kelly_fraction / 2

        # Calculate base size
        base_size = kelly_fraction * max_position

        # Apply position limits
        adjusted_size = max(min_position, min(base_size, max_position))

        # Calculate expected value
        expected_value = (p * avg_win) - (q * avg_loss)

        # Edge required (minimum expected edge to take the trade)
        edge_required = (q * avg_loss) / (avg_win + avg_loss)

        return SizingResult(
            base_size=round(base_size, 2),
            kelly_fraction=round(kelly_fraction, 4),
            adjusted_size=round(adjusted_size, 2),
            edge_required=round(edge_required, 4),
            expected_value=round(expected_value, 2),
            reason="kelly" if kelly_fraction > 0 else "kelly_zero",
        )

    def calculate_from_prices(
        self,
        entry_price: float,
        exit_price: float,
        win_probability: float,
        max_position: float = 250.0,
    ) -> SizingResult:
        """
        Calculate position size from price-based inputs.
        
        Args:
            entry_price: Entry price (e.g., 0.55 for YES)
            exit_price: Expected exit price
            win_probability: Probability of winning (0.0 to 1.0)
            max_position: Maximum position size
            
        Returns:
            SizingResult
        """
        # Calculate P&L from prices
        if exit_price > entry_price:
            # Winning trade
            avg_win = (exit_price - entry_price) * 100  # Convert to USD per share
            avg_loss = entry_price * 100  # Loss if NO wins
        else:
            # Losing trade
            avg_win = (exit_price - entry_price) * 100
            avg_loss = entry_price * 100
        
        return self.calculate(
            win_rate=win_probability,
            avg_win=abs(avg_win),
            avg_loss=abs(avg_loss),
            max_position=max_position,
        )


class DynamicKellyCalculator:
    """
    Dynamic Kelly calculator that adapts based on recent performance.
    
    Uses exponential moving average of win rate and P&L
    to adjust Kelly fraction in real-time.
    """

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
        
        # EMA state
        self._ema_win_rate: Optional[float] = None
        self._ema_avg_win: Optional[float] = None
        self._ema_avg_loss: Optional[float] = None
        self._trade_count = 0

    def update(self, won: bool, pnl: float) -> None:
        """Update EMA state with new trade result."""
        self._trade_count += 1
        
        if self._ema_win_rate is None:
            # Initialize
            self._ema_win_rate = 1.0 if won else 0.0
            self._ema_avg_win = max(0, pnl) if won else 0.0
            self._ema_avg_loss = max(0, -pnl) if not won else 0.0
        else:
            # Update EMA
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

    def calculate(
        self,
        max_position: float = 250.0,
        min_position: float = 5.0,
    ) -> SizingResult:
        """
        Calculate position size using dynamic EMA values.
        """
        if self._trade_count < 10:
            # Not enough data, use conservative defaults
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
    """
    Simple Kelly fraction calculation.
    
    f* = (bp - q) / b
    
    Example:
        >>> kelly_fraction(0.55, 100, 90)
        0.1667
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    
    b = avg_win / avg_loss
    p = win_rate
    q = 1 - p
    
    kelly = (b * p - q) / b
    
    # Clamp to reasonable bounds
    return max(0, min(kelly, 0.25))
