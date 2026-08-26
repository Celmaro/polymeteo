"""Risk Management Configuration for Live Trading.

Defines risk limits, position sizing rules, and safety thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk tolerance levels."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class OrderType(str, Enum):
    """Order types."""

    MARKET = "market"
    LIMIT = "limit"
    TWAP = "twap"
    FOK = "fok"  # Fill or Kill


@dataclass
class PositionLimits:
    """Limits for individual positions."""

    max_position_size_usd: float = 100.0
    min_position_size_usd: float = 10.0
    max_positions_open: int = 3
    max_correlated_positions: int = 2  # Same market/weather event


@dataclass
class DailyLimits:
    """Daily trading limits."""

    max_daily_loss_usd: float = 50.0
    max_daily_profit_usd: float = 200.0
    max_trades_per_day: int = 20
    max_orders_per_minute: int = 5


@dataclass
class DrawdownLimits:
    """Drawdown protection limits."""

    max_drawdown_pct: float = 0.15  # 15%
    warning_drawdown_pct: float = 0.10  # 10%
    max_consecutive_losing_days: int = 3


@dataclass
class OrderLimits:
    """Order execution limits."""

    max_slippage_bps: float = 50.0  # 50 basis points
    min_liquidity_usd: float = 100.0  # Min orderbook depth
    max_order_age_seconds: int = 30
    twap_threshold_usd: float = 75.0  # Use TWAP above this


@dataclass
class QuorumLimits:
    """Quorum trading limits."""

    min_quorum_count: int = 2
    max_quorum_age_seconds: int = 600  # 10 minutes


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    enabled: bool = True
    consecutive_failures: int = 5
    failure_timeout_seconds: float = 60.0
    cooldown_seconds: float = 300.0  # 5 minutes


@dataclass
class RiskLimits:
    """
    Complete risk management configuration.

    Use this class to define all risk parameters for live trading.
    """

    # Risk Level
    risk_level: RiskLevel = RiskLevel.MODERATE

    # Capital
    initial_capital_usd: float = 1000.0
    max_capital_usd: float = 5000.0
    reserve_ratio: float = 0.20  # 20% never traded

    # Position Limits
    position: PositionLimits = field(default_factory=PositionLimits)

    # Daily Limits
    daily: DailyLimits = field(default_factory=DailyLimits)

    # Drawdown
    drawdown: DrawdownLimits = field(default_factory=DrawdownLimits)

    # Order Execution
    order: OrderLimits = field(default_factory=OrderLimits)

    # Quorum
    quorum: QuorumLimits = field(default_factory=QuorumLimits)

    # Circuit Breaker
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    # Whitelists
    allowed_tokens: list[str] | None = None  # None = all allowed
    blocked_wallets: list[str] = field(default_factory=list)

    @classmethod
    def from_risk_level(cls, level: RiskLevel) -> RiskLimits:
        """Create RiskLimits from a predefined risk level."""
        configs = {
            RiskLevel.CONSERVATIVE: cls(
                risk_level=level,
                initial_capital_usd=500.0,
                max_capital_usd=2000.0,
                reserve_ratio=0.30,
                position=PositionLimits(
                    max_position_size_usd=50.0,
                    min_position_size_usd=10.0,
                    max_positions_open=2,
                ),
                daily=DailyLimits(
                    max_daily_loss_usd=25.0,
                    max_daily_profit_usd=100.0,
                    max_trades_per_day=10,
                ),
                drawdown=DrawdownLimits(
                    max_drawdown_pct=0.10,
                    warning_drawdown_pct=0.05,
                ),
                order=OrderLimits(
                    max_slippage_bps=30.0,
                    min_liquidity_usd=200.0,
                    twap_threshold_usd=50.0,
                ),
                quorum=QuorumLimits(
                    min_quorum_count=3,
                ),
            ),
            RiskLevel.MODERATE: cls(
                risk_level=level,
                initial_capital_usd=1000.0,
                max_capital_usd=5000.0,
                reserve_ratio=0.20,
                position=PositionLimits(
                    max_position_size_usd=100.0,
                    min_position_size_usd=10.0,
                    max_positions_open=3,
                ),
                daily=DailyLimits(
                    max_daily_loss_usd=50.0,
                    max_daily_profit_usd=200.0,
                    max_trades_per_day=20,
                ),
                drawdown=DrawdownLimits(
                    max_drawdown_pct=0.15,
                    warning_drawdown_pct=0.10,
                ),
                order=OrderLimits(
                    max_slippage_bps=50.0,
                    min_liquidity_usd=100.0,
                    twap_threshold_usd=75.0,
                ),
                quorum=QuorumLimits(
                    min_quorum_count=2,
                ),
            ),
            RiskLevel.AGGRESSIVE: cls(
                risk_level=level,
                initial_capital_usd=2000.0,
                max_capital_usd=10000.0,
                reserve_ratio=0.15,
                position=PositionLimits(
                    max_position_size_usd=200.0,
                    min_position_size_usd=25.0,
                    max_positions_open=5,
                ),
                daily=DailyLimits(
                    max_daily_loss_usd=100.0,
                    max_daily_profit_usd=500.0,
                    max_trades_per_day=30,
                ),
                drawdown=DrawdownLimits(
                    max_drawdown_pct=0.20,
                    warning_drawdown_pct=0.15,
                ),
                order=OrderLimits(
                    max_slippage_bps=75.0,
                    min_liquidity_usd=50.0,
                    twap_threshold_usd=100.0,
                ),
                quorum=QuorumLimits(
                    min_quorum_count=2,
                ),
            ),
        }

        return configs.get(level, configs[RiskLevel.MODERATE])

    def get_trading_capital(self) -> float:
        """Get capital available for trading."""
        return self.initial_capital_usd * (1 - self.reserve_ratio)

    def get_reserve_capital(self) -> float:
        """Get reserve capital (never traded)."""
        return self.initial_capital_usd * self.reserve_ratio

    def validate_position_size(self, size_usd: float) -> tuple[bool, str]:
        """Validate if a position size is within limits."""
        if size_usd < self.position.min_position_size_usd:
            return False, f"Position too small (min: ${self.position.min_position_size_usd})"

        if size_usd > self.position.max_position_size_usd:
            return False, f"Position too large (max: ${self.position.max_position_size_usd})"

        return True, ""

    def validate_daily_loss(self, current_loss: float) -> tuple[bool, str]:
        """Check if daily loss limit would be breached."""
        if current_loss <= -self.daily.max_daily_loss_usd:
            return False, f"Daily loss limit reached: ${current_loss:.2f}"

        if current_loss <= -self.daily.max_daily_loss_usd * 0.8:
            logger.warning(
                f"⚠️ Approaching daily loss limit: "
                f"${current_loss:.2f} / ${self.daily.max_daily_loss_usd}"
            )

        return True, ""

    def validate_drawdown(self, current_drawdown_pct: float) -> tuple[bool, str]:
        """Check if drawdown limit would be breached."""
        if current_drawdown_pct >= self.drawdown.max_drawdown_pct:
            return False, f"Max drawdown reached: {current_drawdown_pct * 100:.2f}%"

        if current_drawdown_pct >= self.drawdown.warning_drawdown_pct:
            logger.warning(f"⚠️ Elevated drawdown: {current_drawdown_pct * 100:.2f}%")

        return True, ""

    def should_use_twap(self, order_size_usd: float) -> bool:
        """Determine if TWAP should be used for this order."""
        return order_size_usd >= self.order.twap_threshold_usd

    def get_max_slippage_price(self, base_price: float) -> float:
        """Calculate max acceptable price considering slippage."""
        slippage_multiplier = 1 + (self.order.max_slippage_bps / 10000)
        return base_price * slippage_multiplier

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/display."""
        return {
            "risk_level": self.risk_level.value,
            "initial_capital": self.initial_capital_usd,
            "trading_capital": self.get_trading_capital(),
            "reserve_capital": self.get_reserve_capital(),
            "position_limits": {
                "max_size": self.position.max_position_size_usd,
                "min_size": self.position.min_position_size_usd,
                "max_open": self.position.max_positions_open,
            },
            "daily_limits": {
                "max_loss": self.daily.max_daily_loss_usd,
                "max_profit": self.daily.max_daily_profit_usd,
                "max_trades": self.daily.max_trades_per_day,
            },
            "drawdown_limits": {
                "max": self.drawdown.max_drawdown_pct * 100,
                "warning": self.drawdown.warning_drawdown_pct * 100,
            },
            "order_limits": {
                "max_slippage_bps": self.order.max_slippage_bps,
                "min_liquidity": self.order.min_liquidity_usd,
                "twap_threshold": self.order.twap_threshold_usd,
            },
            "quorum": {
                "min_count": self.quorum.min_quorum_count,
            },
        }


class RiskValidator:
    """
    Validates trading decisions against risk limits.

    Use this before every order to ensure compliance.
    """

    def __init__(self, limits: RiskLimits):
        self.limits = limits

        # State tracking
        self._daily_trades = 0
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._last_reset_day = 0

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self._daily_trades = 0
        self._daily_pnl = 0.0
        self._last_reset_day = 0  # Would be actual day number

        logger.info("[RISK] Daily counters reset")

    def validate_order(
        self,
        size_usd: float,
        current_balance: float,
        open_positions: int,
        current_drawdown_pct: float,
        current_daily_loss: float,
    ) -> tuple[bool, str | None]:
        """
        Validate if an order can be placed.

        Returns:
            Tuple of (can_place, error_message)
        """
        # 1. Check position size
        valid, msg = self.limits.validate_position_size(size_usd)
        if not valid:
            return False, msg

        # 2. Check daily loss
        projected_loss = current_daily_loss
        valid, msg = self.limits.validate_daily_loss(projected_loss)
        if not valid:
            return False, msg

        # 3. Check drawdown
        valid, msg = self.limits.validate_drawdown(current_drawdown_pct)
        if not valid:
            return False, msg

        # 4. Check open positions
        if open_positions >= self.limits.position.max_positions_open:
            return False, f"Max open positions reached: {open_positions}"

        # 5. Check capital
        trading_capital = self.limits.get_trading_capital()
        if size_usd > trading_capital:
            return False, f"Insufficient trading capital: ${size_usd:.2f}"

        # 6. Check daily trade count
        if self._daily_trades >= self.limits.daily.max_trades_per_day:
            return False, f"Daily trade limit reached: {self._daily_trades}"

        return True, None

    def record_trade(self, pnl: float) -> None:
        """Record completed trade for daily tracking."""
        self._daily_trades += 1
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Check for consecutive losses limit
        if self._consecutive_losses >= self.limits.drawdown.max_consecutive_losing_days:
            logger.warning(f"⚠️ {self._consecutive_losses} consecutive losing days")

    def get_status(self) -> dict[str, Any]:
        """Get current risk status."""
        return {
            "daily_trades": self._daily_trades,
            "daily_pnl": self._daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "limits": self.limits.to_dict(),
        }


def create_risk_limits(
    level: RiskLevel = RiskLevel.MODERATE,
    **overrides: Any,
) -> RiskLimits:
    """
    Create risk limits with optional overrides.

    Example:
        limits = create_risk_limits(
            RiskLevel.MODERATE,
            initial_capital_usd=1500.0,
            daily_max_loss=75.0,
        )
    """
    limits = RiskLimits.from_risk_level(level)

    # Apply overrides
    for key, value in overrides.items():
        if hasattr(limits, key):
            setattr(limits, key, value)
        else:
            logger.warning(f"Unknown risk limit override: {key}")

    return limits
