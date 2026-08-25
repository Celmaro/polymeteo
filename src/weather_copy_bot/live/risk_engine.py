"""Risk engine with circuit breakers and position limits."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from weather_copy_bot.models import Side, TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limits configuration."""

    # Position limits
    max_position_usd: float = 250.0
    max_total_exposure_usd: float = 1000.0

    # Daily loss limits
    max_daily_loss_usd: float = 500.0
    max_daily_loss_pct: float = 5.0  # % of balance

    # Per-trade limits
    min_trade_size_usd: float = 5.0
    max_trade_size_usd: float = 100.0
    max_trades_per_day: int = 50

    # Latency limits
    max_latency_ms: int = 800
    max_slippage_bps: float = 50.0

    # Liquidity limits
    min_orderbook_depth_usd: float = 1000.0
    min_spread_bps: float = 1.0

    # Emergency stops
    enable_circuit_breaker: bool = True
    circuit_breaker_threshold: float = 0.10  # 10% drawdown


@dataclass
class RiskCheck:
    """Result of a risk check."""

    passed: bool
    rejected: bool = False
    reason: str = ""
    adjustment: float | None = None  # Adjusted size if applicable
    severity: str = "INFO"  # INFO, WARNING, ERROR


@dataclass
class Position:
    """Open position tracking."""

    market_slug: str
    side: Side
    size_usd: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RiskEngine:
    """
    Risk engine with circuit breakers and position management.

    Implements:
    - Position size limits
    - Daily loss limits
    - Circuit breakers for emergency stops
    - Liquidity checks
    - Slippage estimation

    Example:
        engine = RiskEngine(
            limits=RiskLimits(
                max_daily_loss_usd=500.0,
                max_position_usd=250.0,
            )
        )

        # Before executing a trade
        check = engine.check_trade(
            signal=signal,
            size_usd=100.0,
            balance=10000.0,
            daily_pnl=-200.0,
            positions=open_positions,
        )

        if check.rejected:
            logger.warning(f"Trade rejected: {check.reason}")
        elif check.adjustment:
            size = check.adjustment  # Use adjusted size
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
    ):
        self.limits = limits or RiskLimits()
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset daily state."""
        self._daily_loss = 0.0
        self._daily_trades = 0
        self._day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._open_positions: dict[str, Position] = {}
        self._peak_balance = 0.0
        self._circuit_breaker_tripped = False
        self._circuit_breaker_reason: str | None = None

    def _check_day_reset(self) -> None:
        """Reset daily counters if new day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day_key:
            logger.info(f"Resetting daily counters for {today}")
            self._daily_loss = 0.0
            self._daily_trades = 0
            self._day_key = today

    def check_trade(
        self,
        signal: TradeSignal,
        size_usd: float,
        balance: float,
        daily_pnl: float,
        positions: list[Position],
        orderbook_depth: float = 0.0,
    ) -> RiskCheck:
        """
        Check if a trade passes risk controls.

        Args:
            signal: The trading signal
            size_usd: Proposed trade size
            balance: Current account balance
            daily_pnl: Current daily P&L
            positions: Open positions
            orderbook_depth: Available liquidity in orderbook

        Returns:
            RiskCheck with result and any adjustments needed
        """
        self._check_day_reset()

        # Check 1: Circuit breaker
        if self.limits.enable_circuit_breaker and self._circuit_breaker_tripped:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"circuit_breaker_tripped:{self._circuit_breaker_reason}",
                severity="CRITICAL",
            )

        # Check 2: Daily loss limit
        if daily_pnl <= -self.limits.max_daily_loss_usd:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"daily_loss_limit:{daily_pnl:.2f}",
                severity="ERROR",
            )

        # Check 3: Daily loss percentage
        loss_pct = abs(daily_pnl) / balance if balance > 0 else 0
        if loss_pct >= self.limits.max_daily_loss_pct:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"daily_loss_pct:{loss_pct:.2%}",
                severity="ERROR",
            )

        # Check 4: Max trades per day
        if self._daily_trades >= self.limits.max_trades_per_day:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason="max_trades_per_day",
                severity="WARNING",
            )

        # Check 5: Latency
        if signal.latency_ms > self.limits.max_latency_ms:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"latency_too_high:{signal.latency_ms}ms",
                severity="WARNING",
            )

        # Check 6: Slippage estimate
        slippage_estimate = signal.latency_ms * 0.02  # Rough estimate
        if slippage_estimate > self.limits.max_slippage_bps:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"slippage_exceeded:{slippage_estimate:.1f}bps",
                severity="WARNING",
            )

        # Check 7: Trade size limits
        if size_usd < self.limits.min_trade_size_usd:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"size_too_small:{size_usd}",
                severity="WARNING",
            )

        if size_usd > self.limits.max_trade_size_usd:
            # Adjust to max
            return RiskCheck(
                passed=True,
                adjustment=self.limits.max_trade_size_usd,
                reason="adjusted_max_trade_size",
                severity="INFO",
            )

        # Check 8: Total exposure
        total_exposure = sum(p.size_usd for p in positions) + size_usd
        if total_exposure > self.limits.max_total_exposure_usd:
            available = self.limits.max_total_exposure_usd - sum(p.size_usd for p in positions)
            if available <= self.limits.min_trade_size_usd:
                return RiskCheck(
                    passed=False,
                    rejected=True,
                    reason="max_exposure_reached",
                    severity="WARNING",
                )
            return RiskCheck(
                passed=True,
                adjustment=available,
                reason="adjusted_exposure",
                severity="INFO",
            )

        # Check 9: Liquidity
        if orderbook_depth > 0 and orderbook_depth < self.limits.min_orderbook_depth_usd:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason=f"insufficient_liquidity:{orderbook_depth:.0f}",
                severity="WARNING",
            )

        # Check 10: Circuit breaker (drawdown)
        if self.limits.enable_circuit_breaker:
            drawdown = self._calculate_drawdown(balance)
            if drawdown >= self.limits.circuit_breaker_threshold:
                self._circuit_breaker_tripped = True
                self._circuit_breaker_reason = f"drawdown:{drawdown:.2%}"
                return RiskCheck(
                    passed=False,
                    rejected=True,
                    reason=self._circuit_breaker_reason,
                    severity="CRITICAL",
                )

        return RiskCheck(passed=True, reason="all_checks_passed")

    def check_market(
        self,
        market_slug: str,
        bid: float,
        ask: float,
    ) -> RiskCheck:
        """
        Check if a market is tradeable.

        Args:
            market_slug: Market identifier
            bid: Best bid price
            ask: Best ask price

        Returns:
            RiskCheck with market suitability
        """
        # Check spread
        if bid > 0 and ask > 0:
            spread_bps = abs(ask - bid) / ((bid + ask) / 2) * 10000
            if spread_bps > self.limits.max_slippage_bps:
                return RiskCheck(
                    passed=False,
                    rejected=True,
                    reason=f"spread_too_wide:{spread_bps:.0f}bps",
                    severity="WARNING",
                )

        # Check price reasonability
        if bid < 0.01 or ask > 0.99:
            return RiskCheck(
                passed=False,
                rejected=True,
                reason="price_out_of_range",
                severity="WARNING",
            )

        return RiskCheck(passed=True, reason="market_acceptable")

    def _calculate_drawdown(self, current_balance: float) -> float:
        """Calculate current drawdown from peak."""
        if self._peak_balance == 0:
            self._peak_balance = current_balance
            return 0.0

        if current_balance > self._peak_balance:
            self._peak_balance = current_balance
            return 0.0

        return (self._peak_balance - current_balance) / self._peak_balance

    def update_positions(self, positions: list[Position]) -> None:
        """Update tracked open positions."""
        self._open_positions = {p.market_slug: p for p in positions}

    def update_balance(self, balance: float, daily_pnl: float) -> None:
        """Update balance and daily P&L."""
        self._check_day_reset()
        self._daily_loss = daily_pnl
        self._peak_balance = max(self._peak_balance or balance, balance)

    def record_trade(self, pnl: float = 0.0) -> None:
        """Record a trade for daily counters."""
        self._check_day_reset()
        self._daily_trades += 1
        if pnl:
            self._daily_loss += pnl

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        logger.warning("Circuit breaker manually reset")
        self._circuit_breaker_tripped = False
        self._circuit_breaker_reason = None

    def get_state(self) -> dict:
        """Get current risk engine state."""
        return {
            "circuit_breaker_tripped": self._circuit_breaker_tripped,
            "circuit_breaker_reason": self._circuit_breaker_reason,
            "daily_trades": self._daily_trades,
            "daily_pnl": self._daily_loss,
            "peak_balance": self._peak_balance,
            "open_positions": len(self._open_positions),
            "drawdown": self._calculate_drawdown(0),  # Requires balance to be set
        }


class LiquidityChecker:
    """
    Checks orderbook liquidity before executing trades.

    Prevents trading in illiquid markets.
    """

    def __init__(self, min_depth_usd: float = 1000.0, min_levels: int = 3):
        self.min_depth_usd = min_depth_usd
        self.min_levels = min_levels

    def check_depth(
        self,
        levels: list[tuple[float, float]],  # [(price, size), ...]
        side: Side,
        order_size: float,
    ) -> tuple[bool, str]:
        """
        Check if there's sufficient liquidity for an order.

        Args:
            levels: Orderbook levels (price, size)
            side: Order side
            order_size: Desired order size

        Returns:
            (sufficient, reason)
        """
        if not levels:
            return False, "empty_orderbook"

        # Calculate total depth at each level
        cumulative = 0.0
        for _price, size in levels:
            cumulative += size
            if cumulative >= order_size:
                break

        if cumulative < order_size:
            return False, f"insufficient_depth:{cumulative:.0f}"

        return True, "ok"

    def estimate_slippage(
        self,
        levels: list[tuple[float, float]],
        order_size: float,
        side: Side,
    ) -> float:
        """
        Estimate slippage for an order.

        Returns slippage in basis points.
        """
        if not levels:
            return 1000.0  # Maximum slippage

        # Best price
        best_price = levels[0][0]

        # Calculate volume-weighted average fill price
        remaining = order_size
        total_cost = 0.0

        for price, size in levels:
            fill = min(remaining, size)
            total_cost += fill * price
            remaining -= fill
            if remaining <= 0:
                break

        if remaining > 0:
            return 1000.0  # Couldn't fill

        avg_price = total_cost / order_size

        # Slippage calculation
        if side == Side.BUY:
            slippage = (avg_price - best_price) / best_price
        else:
            slippage = (best_price - avg_price) / best_price

        return slippage * 10000  # Convert to bps
