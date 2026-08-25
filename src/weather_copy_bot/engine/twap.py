"""TWAP Slicer for Large Orders.

Splits large orders into smaller slices to minimize market impact.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SliceStatus(str, Enum):
    """Status of a TWAP slice."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TWAPSlice:
    """A single slice of a TWAP order."""

    slice_id: str
    slice_number: int
    total_slices: int
    size_usd: float
    price_limit: float
    status: SliceStatus = SliceStatus.PENDING
    submitted_at: float | None = None
    filled_at: float | None = None
    fill_price: float | None = None
    fill_amount: float = 0.0
    error: str | None = None


@dataclass
class TWAPExecution:
    """Complete TWAP execution result."""

    execution_id: str
    token_id: str
    side: str
    total_size_usd: float
    slices: list[TWAPSlice]
    status: SliceStatus = SliceStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    avg_fill_price: float = 0.0
    total_filled: float = 0.0
    total_cost: float = 0.0


class TWAPSlicer:
    """
    Time-Weighted Average Price (TWAP) executor.

    Splits large orders into smaller slices to:
    - Minimize market impact
    - Reduce slippage
    - Avoid triggering orderbook imbalance
    """

    def __init__(
        self,
        min_slice_size_usd: float = 10.0,  # Don't slice below $10
        max_slices: int = 20,
        slice_interval_seconds: int = 30,
        price_deviation_threshold: float = 0.02,  # 2% price move threshold
        timeout_seconds: int = 600,  # 10 min max
    ):
        """
        Initialize TWAP Slicer.

        Args:
            min_slice_size_usd: Minimum size per slice
            max_slices: Maximum number of slices
            slice_interval_seconds: Time between slices
            price_deviation_threshold: Cancel if price moves more than this
            timeout_seconds: Maximum time for entire execution
        """
        self.min_slice_size = min_slice_size_usd
        self.max_slices = max_slices
        self.slice_interval = slice_interval_seconds
        self.price_threshold = price_deviation_threshold
        self.timeout = timeout_seconds

        # Active executions
        self._executions: dict[str, TWAPExecution] = {}

        # Stats
        self._stats = {
            "executions_started": 0,
            "executions_completed": 0,
            "executions_cancelled": 0,
            "executions_failed": 0,
            "slices_submitted": 0,
            "slices_filled": 0,
            "slices_failed": 0,
            "total_savings_bps": 0,  # Slippage savings vs. single order
        }

    def _calculate_slices(self, total_size_usd: float, initial_price: float) -> list[TWAPSlice]:
        """Calculate slice sizes."""
        num_slices = min(max(1, int(total_size_usd / self.min_slice_size)), self.max_slices)

        slice_size = total_size_usd / num_slices

        slices = []
        for i in range(num_slices):
            # Add small random variation to price limit
            # to avoid always hitting same price level
            variation = (i % 3 - 1) * 0.001  # -0.1% to +0.1%
            price_limit = initial_price * (1 + variation)

            slices.append(
                TWAPSlice(
                    slice_id=f"{i}",
                    slice_number=i + 1,
                    total_slices=num_slices,
                    size_usd=slice_size,
                    price_limit=price_limit,
                )
            )

        return slices

    async def execute(
        self,
        execution_id: str,
        token_id: str,
        side: str,
        total_size_usd: float,
        initial_price: float,
        executor_fn: Callable[[TWAPSlice], Awaitable[bool]],
        price_check_fn: Callable[[str], Awaitable[float]],
    ) -> TWAPExecution:
        """
        Execute a TWAP order.

        Args:
            execution_id: Unique execution ID
            token_id: Token to trade
            side: BUY or SELL
            total_size_usd: Total order size in USD
            initial_price: Initial market price
            executor_fn: Async function to execute a slice
            price_check_fn: Async function to get current price

        Returns:
            TWAPExecution result
        """
        logger.info(
            f"[TWAP] Starting execution {execution_id}: "
            f"{side} ${total_size_usd} @ {initial_price:.4f}"
        )

        # Create slices
        slices = self._calculate_slices(total_size_usd, initial_price)

        # Create execution
        execution = TWAPExecution(
            execution_id=execution_id,
            token_id=token_id,
            side=side,
            total_size_usd=total_size_usd,
            slices=slices,
        )

        self._executions[execution_id] = execution
        self._stats["executions_started"] += 1

        try:
            await self._execute_slices(execution, executor_fn, price_check_fn, initial_price)

            if execution.total_filled >= total_size_usd * 0.99:  # 99% filled
                execution.status = SliceStatus.FILLED
                self._stats["executions_completed"] += 1
            else:
                execution.status = SliceStatus.PARTIAL
                self._stats["executions_cancelled"] += 1

        except asyncio.TimeoutError:
            execution.status = SliceStatus.FAILED
            execution.error = "Timeout"
            self._stats["executions_failed"] += 1

        except Exception as e:
            execution.status = SliceStatus.FAILED
            execution.error = str(e)
            self._stats["executions_failed"] += 1

        execution.completed_at = time.time()

        # Calculate stats
        if execution.total_filled > 0:
            execution.avg_fill_price = execution.total_cost / execution.total_filled

        logger.info(
            f"[TWAP] Execution {execution_id} completed: "
            f"status={execution.status.value}, "
            f"filled=${execution.total_filled:.2f} @ {execution.avg_fill_price:.4f}"
        )

        return execution

    async def _execute_slices(
        self,
        execution: TWAPExecution,
        executor_fn: Callable[[TWAPSlice], Awaitable[bool]],
        price_check_fn: Callable[[str], Awaitable[float]],
        initial_price: float,
    ) -> None:
        """Execute all slices with interval."""
        start_time = time.time()

        for i, slice_ in enumerate(execution.slices):
            # Check timeout
            if time.time() - start_time > self.timeout:
                logger.warning(f"[TWAP] Execution {execution.execution_id} timed out")
                raise asyncio.TimeoutError()

            # Check price deviation
            try:
                current_price = await price_check_fn(execution.token_id)
                price_change = abs(current_price - initial_price) / initial_price

                if price_change > self.price_threshold:
                    logger.warning(
                        f"[TWAP] Price moved {price_change * 100:.2f}% "
                        f"(threshold: {self.price_threshold * 100}%), skipping remaining slices"
                    )
                    # Mark remaining slices as skipped
                    for remaining in execution.slices[i:]:
                        remaining.status = SliceStatus.SKIPPED
                    return

            except Exception as e:
                logger.warning(f"[TWAP] Price check failed: {e}, continuing...")

            # Execute slice
            slice_.status = SliceStatus.SUBMITTED
            slice_.submitted_at = time.time()
            self._stats["slices_submitted"] += 1

            try:
                success = await executor_fn(slice_)

                if success:
                    slice_.status = SliceStatus.FILLED
                    slice_.filled_at = time.time()
                    slice_.fill_amount = slice_.size_usd
                    slice_.fill_price = slice_.price_limit

                    execution.total_filled += slice_.size_usd
                    execution.total_cost += slice_.size_usd * slice_.price_limit

                    self._stats["slices_filled"] += 1

                    logger.info(
                        f"[TWAP] Slice {slice_.slice_number}/{slice_.total_slices} filled: "
                        f"${slice_.size_usd:.2f}"
                    )
                else:
                    slice_.status = SliceStatus.FAILED
                    self._stats["slices_failed"] += 1

            except Exception as e:
                slice_.status = SliceStatus.FAILED
                slice_.error = str(e)
                self._stats["slices_failed"] += 1
                logger.error(f"[TWAP] Slice {slice_.slice_number} failed: {e}")

            # Wait before next slice (except for last slice)
            if i < len(execution.slices) - 1:
                await asyncio.sleep(self.slice_interval)

        # Calculate slippage savings
        if execution.total_filled > 0:
            # Compare to single large order at worst price
            worst_price = max(s.price_limit for s in execution.slices)
            avg_price = execution.avg_fill_price

            # Savings in basis points
            savings_bps = abs(worst_price - avg_price) / avg_price * 10000
            self._stats["total_savings_bps"] += int(savings_bps)

    def get_execution(self, execution_id: str) -> TWAPExecution | None:
        """Get an execution by ID."""
        return self._executions.get(execution_id)

    def get_stats(self) -> dict:
        """Get TWAP statistics."""
        return {
            **self._stats,
            "avg_savings_bps": (
                self._stats["total_savings_bps"] / max(1, self._stats["executions_completed"])
            ),
            "slice_success_rate": (
                self._stats["slices_filled"] / max(1, self._stats["slices_submitted"]) * 100
            ),
        }


class TWAPIntegration:
    """
    Integration layer for TWAP with Risk Engine.

    Automatically decides when to use TWAP based on order size
    and market conditions.
    """

    def __init__(
        self,
        twap_slicer: TWAPSlicer,
        risk_engine,  # RiskEngine instance
        twap_threshold_usd: float = 100.0,  # Use TWAP above this size
    ):
        """
        Initialize TWAP Integration.

        Args:
            twap_slicer: TWAPSlicer instance
            risk_engine: RiskEngine for validation
            twap_threshold_usd: Order size threshold for TWAP
        """
        self.twap = twap_slicer
        self.risk = risk_engine
        self.threshold = twap_threshold_usd

    async def execute_with_twap(
        self,
        token_id: str,
        side: str,
        size_usd: float,
        price: float,
        executor_fn: Callable,
        price_check_fn: Callable,
    ) -> TWAPExecution | None:
        """
        Execute order, using TWAP if size exceeds threshold.

        Args:
            token_id: Token to trade
            side: BUY or SELL
            size_usd: Order size in USD
            price: Current price
            executor_fn: Slice executor function
            price_check_fn: Price check function

        Returns:
            TWAPExecution if TWAP used, None otherwise
        """
        # Check if TWAP should be used
        if size_usd <= self.threshold:
            logger.info(
                f"[TWAP-Int] Order size ${size_usd:.2f} below threshold, executing directly"
            )
            return None

        # Risk check
        risk_check = self.risk.check_size_limits(size_usd)
        if not risk_check.passed:
            logger.warning(f"[TWAP-Int] Risk check failed: {risk_check.reason}")
            return None

        # Execute TWAP
        import uuid

        execution_id = str(uuid.uuid4())

        return await self.twap.execute(
            execution_id=execution_id,
            token_id=token_id,
            side=side,
            total_size_usd=size_usd,
            initial_price=price,
            executor_fn=executor_fn,
            price_check_fn=price_check_fn,
        )
