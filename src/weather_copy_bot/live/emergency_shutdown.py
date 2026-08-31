"""Emergency Shutdown System for Live Trading.

Implements automated circuit breakers and manual shutdown capabilities.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weather_copy_bot.live.order_queue import OrderQueue
    from weather_copy_bot.live.signer import CLOBExecutor

logger = logging.getLogger(__name__)


class ShutdownReason(str, Enum):
    """Reasons for emergency shutdown."""

    MANUAL = "manual"
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWING_LIMIT = "drawing_limit"
    CONNECTIVITY_FAILURE = "connectivity_failure"
    API_ERROR = "api_error"
    RISK_LIMIT_BREACH = "risk_limit_breach"
    UNKNOWN = "unknown"


class SystemState(str, Enum):
    """Current system operational state."""

    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    PAUSED = "paused"


@dataclass
class ShutdownEvent:
    """Record of a shutdown event."""

    reason: ShutdownReason
    timestamp: float
    details: str
    positions_closed: int
    pending_orders_cancelled: int
    balance_at_shutdown: float
    pnl_at_shutdown: float


@dataclass
class CircuitBreakerState:
    """State of circuit breaker monitoring."""

    consecutive_failures: int = 0
    last_failure_time: float | None = None
    is_tripped: bool = False
    trip_reason: str | None = None


class EmergencyShutdown:
    """
    Emergency shutdown system for live trading.

    Features:
    - Manual shutdown via code
    - Automated circuit breakers (daily loss, drawdown)
    - Connectivity failure detection
    - Graceful position/orders cleanup

    Trigger conditions:
    - Daily loss limit reached
    - Circuit breaker triggered
    - Connectivity failure
    - Manual API call
    """

    def __init__(
        self,
        max_daily_loss_usd: float = 50.0,
        max_drawdown_pct: float = 0.15,
        max_consecutive_failures: int = 5,
        failure_timeout_seconds: float = 60.0,
    ):
        """
        Initialize Emergency Shutdown.

        Args:
            max_daily_loss_usd: Maximum daily loss before shutdown
            max_drawdown_pct: Maximum drawdown percentage before shutdown
            max_consecutive_failures: Failures before circuit breaker trips
            failure_timeout_seconds: Timeout to reset failure counter
        """
        self.max_daily_loss = max_daily_loss_usd
        self.max_drawdown = max_drawdown_pct
        self.max_failures = max_consecutive_failures
        self.failure_timeout = failure_timeout_seconds

        # Dependencies (set via set_dependencies)
        self._order_queue: OrderQueue | None = None
        self._executor: CLOBExecutor | None = None
        self._get_balance_fn: Callable[[], Awaitable[float]] | None = None
        self._get_positions_fn: Callable[[], Awaitable[list[dict]]] | None = None

        # State
        self._state = SystemState.RUNNING
        self._shutdown_log: list[ShutdownEvent] = []
        self._circuit_breaker = CircuitBreakerState()
        self._daily_loss = 0.0
        self._peak_balance = 0.0

        # Locks
        self._shutdown_lock = asyncio.Lock()
        # Guards ``_daily_loss``/``_peak_balance`` against races between the
        # async check loop and the sync reset path (and any sync stats read).
        self._pnl_lock = RLock()

        logger.info(
            f"[SHUTDOWN] Emergency shutdown initialized: "
            f"max_daily_loss=${self.max_daily_loss}, "
            f"max_drawdown={self.max_drawdown * 100}%"
        )

    def set_dependencies(
        self,
        order_queue: OrderQueue,
        executor: CLOBExecutor,
        get_balance_fn: Callable[[], Awaitable[float]],
        get_positions_fn: Callable[[], Awaitable[list[dict]]],
    ) -> None:
        """Set dependencies for shutdown operations."""
        self._order_queue = order_queue
        self._executor = executor
        self._get_balance_fn = get_balance_fn
        self._get_positions_fn = get_positions_fn

    async def emergency_stop(
        self,
        reason: ShutdownReason,
        details: str = "",
    ) -> ShutdownEvent:
        """
        Execute emergency shutdown.

        Steps:
        1. Acquire lock to prevent concurrent shutdowns
        2. Cancel all pending orders
        3. Close all positions (paper mode: mark closed)
        4. Log event
        5. Set system state to SHUTDOWN
        """
        async with self._shutdown_lock:
            if self._state == SystemState.SHUTDOWN:
                logger.warning("[SHUTDOWN] Already shut down, ignoring")
                return self._shutdown_log[-1] if self._shutdown_log else None

            if self._state == SystemState.SHUTTING_DOWN:
                logger.warning("[SHUTDOWN] Already shutting down")
                return None

            self._state = SystemState.SHUTTING_DOWN
            start_time = time.time()

            logger.critical(f"[SHUTDOWN] EMERGENCY STOP TRIGGERED: {reason.value} - {details}")

            # Get current state
            balance = 0.0
            if self._get_balance_fn:
                try:
                    balance = await self._get_balance_fn()
                except Exception as e:
                    logger.warning(
                        f"[SHUTDOWN] Failed to fetch balance before shutdown: {e}"
                    )

            # Step 1: Cancel pending orders
            pending_cancelled = 0
            if self._order_queue:
                try:
                    pending = self._order_queue.get_pending_orders()
                    for order in pending:
                        await self._order_queue.cancel_order(order.order_id)
                        pending_cancelled += 1
                    logger.info(f"[SHUTDOWN] Cancelled {pending_cancelled} pending orders")
                except Exception as e:
                    logger.error(f"[SHUTDOWN] Error cancelling orders: {e}")

            # Step 2: Close positions, isolating failures so one bad close
            # cannot abort the remaining liquidations
            positions_closed = 0
            position_failures: list[str] = []
            if self._executor and self._get_positions_fn:
                try:
                    positions = await self._get_positions_fn()
                except Exception as e:
                    logger.error(f"[SHUTDOWN] Error fetching positions: {e}")
                    positions = []
                for pos in positions:
                    position_id = pos.get("position_id") if isinstance(pos, dict) else pos
                    try:
                        await self._executor.close_position(position_id)
                        positions_closed += 1
                    except Exception as e:
                        logger.error(f"[SHUTDOWN] Failed to close position {position_id}: {e}")
                        position_failures.append(f"{position_id}: {e}")
                logger.info(
                    f"[SHUTDOWN] Closed {positions_closed} positions "
                    f"({len(position_failures)} failures)"
                )

            # Step 3: Create event (append close failures so they reach the
            # log and the persisted event)
            full_details = details
            if position_failures:
                failure_summary = "; ".join(position_failures)
                full_details = (
                    f"{details} | failed closes: {failure_summary}"
                    if details
                    else f"failed closes: {failure_summary}"
                )

            with self._pnl_lock:
                event = ShutdownEvent(
                    reason=reason,
                    timestamp=time.time(),
                    details=full_details,
                    positions_closed=positions_closed,
                    pending_orders_cancelled=pending_cancelled,
                    balance_at_shutdown=balance,
                    pnl_at_shutdown=self._daily_loss,
                )
                self._shutdown_log.append(event)

            # Step 4: Set final state
            self._state = SystemState.SHUTDOWN

            logger.critical(
                f"[SHUTDOWN] Complete. "
                f"Closed {positions_closed} positions, "
                f"Cancelled {pending_cancelled} orders, "
                f"Duration: {time.time() - start_time:.2f}s"
            )

            return event

    async def check_emergency_conditions(
        self,
        current_pnl: float,
        current_balance: float,
        open_positions_count: int,
    ) -> ShutdownReason | None:
        """
        Check if any emergency condition is met.

        Args:
            current_pnl: Current daily P&L
            current_balance: Current account balance
            open_positions_count: Number of open positions

        Returns:
            ShutdownReason if emergency triggered, None otherwise
        """
        # Check daily loss
        if current_pnl <= -self.max_daily_loss:
            return ShutdownReason.DAILY_LOSS_LIMIT

        # Update peak balance
        with self._pnl_lock:
            if current_balance > self._peak_balance:
                self._peak_balance = current_balance

            # Check drawdown
            if self._peak_balance > 0:
                drawdown = (self._peak_balance - current_balance) / self._peak_balance
                if drawdown >= self.max_drawdown:
                    return ShutdownReason.DRAWING_LIMIT

            # Update daily loss tracking
            self._daily_loss = current_pnl

        return None

    def record_failure(self, error: str) -> None:
        """
        Record an operation failure for circuit breaker.

        Args:
            error: Error message
        """
        now = time.time()

        # Reset counter if timeout passed
        if (
            self._circuit_breaker.last_failure_time
            and now - self._circuit_breaker.last_failure_time > self.failure_timeout
        ):
            self._circuit_breaker.consecutive_failures = 0

        self._circuit_breaker.consecutive_failures += 1
        self._circuit_breaker.last_failure_time = now

        logger.warning(
            f"[CIRCUIT] Failure {self._circuit_breaker.consecutive_failures}/"
            f"{self.max_failures}: {error}"
        )

        # Check if should trip
        if self._circuit_breaker.consecutive_failures >= self.max_failures:
            self._circuit_breaker.is_tripped = True
            self._circuit_breaker.trip_reason = f"{self.max_failures} consecutive failures"
            logger.critical(f"[CIRCUIT] CIRCUIT BREAKER TRIPPED: {error}")

    def record_success(self) -> None:
        """Record successful operation (resets failure counter)."""
        if self._circuit_breaker.consecutive_failures > 0:
            logger.debug(
                f"[CIRCUIT] Resetting failure counter "
                f"(was {self._circuit_breaker.consecutive_failures})"
            )
        self._circuit_breaker.consecutive_failures = 0
        self._circuit_breaker.last_failure_time = None

    def is_circuit_tripped(self) -> bool:
        """Check if circuit breaker is tripped."""
        return self._circuit_breaker.is_tripped

    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker (requires confirmation)."""
        logger.warning("[CIRCUIT] Circuit breaker manually reset")
        self._circuit_breaker = CircuitBreakerState()

    def is_shutdown(self) -> bool:
        """Check if system is in shutdown state."""
        return self._state == SystemState.SHUTDOWN

    def is_running(self) -> bool:
        """Check if system is running normally."""
        return self._state == SystemState.RUNNING

    def get_state(self) -> SystemState:
        """Get current system state."""
        return self._state

    def get_shutdown_log(self) -> list[ShutdownEvent]:
        """Get all shutdown events."""
        return self._shutdown_log.copy()

    def get_stats(self) -> dict[str, Any]:
        """Get shutdown system statistics."""
        with self._pnl_lock:
            stats = {
                "state": self._state.value,
                "total_shutdowns": len(self._shutdown_log),
                "daily_pnl": self._daily_loss,
                "peak_balance": self._peak_balance,
                "circuit_breaker": {
                    "tripped": self._circuit_breaker.is_tripped,
                    "consecutive_failures": self._circuit_breaker.consecutive_failures,
                    "trip_reason": self._circuit_breaker.trip_reason,
                },
            }
        return stats

    def reset_daily_tracking(self) -> None:
        """Reset daily P&L tracking (call at start of trading day)."""
        with self._pnl_lock:
            self._daily_loss = 0.0
        logger.info("[SHUTDOWN] Daily tracking reset")


class ShutdownGuard:
    """
    Guard decorator/wrapper to prevent operations during shutdown.

    Usage:
        shutdown_guard = ShutdownGuard(emergency_shutdown)

        @shutdown_guard
        async def execute_order(...):
            ...
    """

    def __init__(self, emergency_shutdown: EmergencyShutdown):
        self.shutdown = emergency_shutdown

    def __call__(self, func: Callable) -> Callable:
        """Decorator to guard async functions."""

        async def wrapper(*args, **kwargs):
            if self.shutdown.is_shutdown():
                raise RuntimeError(f"Cannot execute {func.__name__}: system is shutdown")
            if self.shutdown.is_circuit_tripped():
                raise RuntimeError(f"Cannot execute {func.__name__}: circuit breaker tripped")
            try:
                result = await func(*args, **kwargs)
                self.shutdown.record_success()
                return result
            except Exception as e:
                self.shutdown.record_failure(str(e))
                raise

        return wrapper


# Convenience function for creating shutdown guard
def create_shutdown_guard(
    max_daily_loss: float = 50.0,
    max_drawdown_pct: float = 0.15,
) -> EmergencyShutdown:
    """Create a pre-configured emergency shutdown system."""
    return EmergencyShutdown(
        max_daily_loss_usd=max_daily_loss,
        max_drawdown_pct=max_drawdown_pct,
    )
