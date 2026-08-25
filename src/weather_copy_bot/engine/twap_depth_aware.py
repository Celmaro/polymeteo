"""Depth-Aware TWAP Slicer for Large Orders.

Extends TWAPSlicer with liquidity-based slice sizing.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from weather_copy_bot.analysis.obi_filter import OBIAnalyzer, OrderBook

logger = logging.getLogger(__name__)


class DepthAwareStatus(str, Enum):
    """Status of depth-aware execution."""

    PENDING = "pending"
    ADJUSTING = "adjusting"
    EXECUTING = "executing"
    COMPLETED = "completed"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    FAILED = "failed"


@dataclass
class DepthSlice:
    """A slice with depth information."""

    slice_id: str
    slice_number: int
    total_slices: int
    size_usd: float
    size_adjusted: float  # Adjusted based on depth
    price_limit: float
    depth_available: float  # Available liquidity at this level
    status: str = "pending"
    filled_at: float | None = None
    fill_price: float | None = None


@dataclass
class DepthAwareExecution:
    """Complete depth-aware TWAP execution result."""

    execution_id: str
    token_id: str
    side: str
    total_size_usd: float
    total_filled: float = 0.0
    avg_fill_price: float = 0.0
    total_cost: float = 0.0
    status: DepthAwareStatus = DepthAwareStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    slices: list[DepthSlice] = field(default_factory=list)
    depth_adjusted_count: int = 0
    skipped_count: int = 0
    error: str | None = None


@dataclass
class LiquidityEstimate:
    """Estimate of available liquidity."""

    depth_at_price: float  # Available depth at target price
    weighted_depth: float  # Depth weighted by price levels
    max_slice_size: float  # Recommended max slice size
    is_sufficient: bool  # True if depth is sufficient for execution
    spread_bps: float  # Current spread in bps


class LiquidityEstimator:
    """
    Estimates available liquidity for order execution.

    Uses order book data to determine how much can be filled
    at each price level without excessive slippage.
    """

    def __init__(
        self,
        depth_levels: int = 5,
        max_slippage_bps: float = 50.0,
        min_depth_ratio: float = 0.3,  # Min 30% of order must be fillable
    ):
        """
        Initialize Liquidity Estimator.

        Args:
            depth_levels: Number of price levels to consider
            max_slippage_bps: Maximum acceptable slippage
            min_depth_ratio: Minimum ratio of order that should be fillable
        """
        self.depth_levels = depth_levels
        self.max_slippage = max_slippage_bps / 10000
        self.min_depth_ratio = min_depth_ratio

    def estimate_liquidity(
        self,
        order_book,  # OrderBook instance
        side: str,
        target_price: float,
        order_size: float,
    ) -> LiquidityEstimate:
        """
        Estimate liquidity for an order.

        Args:
            order_book: OrderBook with bids and asks
            side: BUY or SELL
            target_price: Target entry price
            order_size: Total order size

        Returns:
            LiquidityEstimate with recommendations
        """
        if side.upper() == "BUY":
            levels = [(level.price, level.size) for level in order_book.asks]
        else:
            levels = [(level.price, level.size) for level in order_book.bids]

        if not levels:
            return LiquidityEstimate(
                depth_at_price=0.0,
                weighted_depth=0.0,
                max_slice_size=0.0,
                is_sufficient=False,
                spread_bps=0.0,
            )

        # Calculate depth at target price level
        depth_at_price = 0.0
        for price, size in levels:
            if (side.upper() == "BUY" and price <= target_price * (1 + self.max_slippage)) or (
                side.upper() == "SELL" and price >= target_price * (1 - self.max_slippage)
            ):
                depth_at_price += size

        # Calculate weighted depth
        weighted_depth = sum(size for _, size in levels[: self.depth_levels])

        # Calculate max slice size (cap at available depth)
        max_slice = min(depth_at_price, weighted_depth * 0.5)

        # Check sufficiency
        is_sufficient = depth_at_price >= order_size * self.min_depth_ratio

        # Spread calculation
        spread_bps = order_book.spread_bps if hasattr(order_book, "spread_bps") else 0.0

        return LiquidityEstimate(
            depth_at_price=round(depth_at_price, 2),
            weighted_depth=round(weighted_depth, 2),
            max_slice_size=round(max_slice, 2),
            is_sufficient=is_sufficient,
            spread_bps=round(spread_bps, 2),
        )

    def calculate_adaptive_slice_size(
        self,
        liquidity: LiquidityEstimate,
        base_size: float,
        slice_number: int,
    ) -> float:
        """
        Calculate adaptive slice size based on liquidity.

        Args:
            liquidity: Current liquidity estimate
            base_size: Base slice size from TWAP
            slice_number: Current slice number

        Returns:
            Adjusted slice size
        """
        if not liquidity.is_sufficient:
            # No execution possible
            return 0.0

        if liquidity.max_slice_size <= 0:
            return 0.0

        # Start with base size, cap at available depth
        # Apply decay factor for later slices (reduce exposure)
        decay_factor = 1.0 - (slice_number * 0.05)  # 5% reduction per slice

        adaptive_size = min(
            base_size * decay_factor,
            liquidity.max_slice_size,
        )

        # Ensure minimum executable size
        return max(5.0, adaptive_size)


class TWAPSlicerDepthAware:
    """
    Depth-Aware TWAP Slicer.

    Extends TWAPSlicer with:
    - Order book depth awareness
    - Adaptive slice sizing based on liquidity
    - OBI filter integration
    - Dynamic slice count adjustment
    """

    def __init__(
        self,
        # TWAP base config
        min_slice_size_usd: float = 10.0,
        max_slices: int = 20,
        slice_interval_seconds: int = 30,
        price_deviation_threshold: float = 0.02,
        timeout_seconds: int = 600,
        # Depth-aware config
        liquidity_estimator: LiquidityEstimator | None = None,
        obi_analyzer: Optional["OBIAnalyzer"] = None,  # From analysis.obi_filter
        depth_check_interval: int = 5,  # Check depth every N slices
        min_liquidity_threshold: float = 0.3,  # Min 30% of order must be fillable
    ):
        """
        Initialize Depth-Aware TWAP Slicer.

        Args:
            min_slice_size_usd: Minimum size per slice
            max_slices: Maximum number of slices
            slice_interval_seconds: Time between slices
            price_deviation_threshold: Cancel if price moves more than this
            timeout_seconds: Maximum time for entire execution
            liquidity_estimator: LiquidityEstimator instance
            obi_analyzer: OBIAnalyzer for market microstructure
            depth_check_interval: Check depth every N slices
            min_liquidity_threshold: Minimum liquidity ratio
        """
        # TWAP base config
        self.min_slice_size = min_slice_size_usd
        self.max_slices = max_slices
        self.slice_interval = slice_interval_seconds
        self.price_threshold = price_deviation_threshold
        self.timeout = timeout_seconds

        # Depth-aware config
        self.liquidity_estimator = liquidity_estimator or LiquidityEstimator()
        self.obi_analyzer = obi_analyzer
        self.depth_check_interval = depth_check_interval
        self.min_liquidity_threshold = min_liquidity_threshold

        # Active executions
        self._executions: dict[str, DepthAwareExecution] = {}

        # Stats
        self._stats = {
            "executions_started": 0,
            "executions_completed": 0,
            "executions_insufficient_liquidity": 0,
            "executions_failed": 0,
            "slices_adjusted": 0,
            "slices_skipped": 0,
            "depth_checks": 0,
            "avg_depth_utilization": 0.0,  # % of depth used
        }

    def _get_order_book_provider(self) -> Callable | None:
        """Get order book provider function if available."""
        # This would be injected in production
        return None

    async def _get_order_book(self, token_id: str) -> Optional["OrderBook"]:
        """Get order book for token."""
        # In production, this would call the order book provider
        # For now, return None to use fallback logic
        provider = self._get_order_book_provider()
        if provider:
            return await provider(token_id)
        return None

    def _calculate_adaptive_slices(
        self,
        total_size_usd: float,
        initial_price: float,
        initial_liquidity: LiquidityEstimate,
    ) -> list[DepthSlice]:
        """Calculate initial slices with adaptive sizing."""
        # Calculate base number of slices
        base_num_slices = min(max(1, int(total_size_usd / self.min_slice_size)), self.max_slices)

        # Adjust number of slices based on liquidity
        # If liquidity is low, more slices (smaller) needed
        if initial_liquidity.max_slice_size > 0:
            adjusted_slices = min(
                max(1, int(total_size_usd / initial_liquidity.max_slice_size)), self.max_slices
            )
            base_num_slices = max(base_num_slices, adjusted_slices)

        slice_size = total_size_usd / base_num_slices

        slices = []
        for i in range(base_num_slices):
            # Adaptive price limit
            variation = (i % 3 - 1) * 0.001
            price_limit = initial_price * (1 + variation)

            # Adaptive size based on liquidity
            adjusted_size = self.liquidity_estimator.calculate_adaptive_slice_size(
                initial_liquidity,
                slice_size,
                i,
            )

            slices.append(
                DepthSlice(
                    slice_id=f"slice_{i}",
                    slice_number=i + 1,
                    total_slices=base_num_slices,
                    size_usd=slice_size,
                    size_adjusted=adjusted_size,
                    price_limit=price_limit,
                    depth_available=initial_liquidity.max_slice_size,
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
        executor_fn: Callable[["DepthSlice"], Awaitable[bool]],
        price_check_fn: Callable[[str], Awaitable[float]],
    ) -> DepthAwareExecution:
        """
        Execute a depth-aware TWAP order.

        Args:
            execution_id: Unique execution ID
            token_id: Token to trade
            side: BUY or SELL
            total_size_usd: Total order size in USD
            initial_price: Initial market price
            executor_fn: Async function to execute a slice
            price_check_fn: Async function to get current price

        Returns:
            DepthAwareExecution result
        """
        logger.info(
            f"[TWAP-D] Starting depth-aware execution {execution_id}: "
            f"{side} ${total_size_usd} @ {initial_price:.4f}"
        )

        # Get order book for initial liquidity estimate
        order_book = await self._get_order_book(token_id)

        # Calculate initial liquidity estimate
        if order_book:
            initial_liquidity = self.liquidity_estimator.estimate_liquidity(
                order_book, side, initial_price, total_size_usd
            )
        else:
            # Fallback: assume sufficient liquidity
            initial_liquidity = LiquidityEstimate(
                depth_at_price=total_size_usd * 2,
                weighted_depth=total_size_usd * 3,
                max_slice_size=total_size_usd / 10,
                is_sufficient=True,
                spread_bps=0.0,
            )

        # Check initial liquidity
        if not initial_liquidity.is_sufficient:
            execution = DepthAwareExecution(
                execution_id=execution_id,
                token_id=token_id,
                side=side,
                total_size_usd=total_size_usd,
                status=DepthAwareStatus.INSUFFICIENT_LIQUIDITY,
                error=f"Insufficient liquidity: only ${initial_liquidity.depth_at_price:.2f} available",
            )
            self._stats["executions_insufficient_liquidity"] += 1
            return execution

        # Create slices
        slices = self._calculate_adaptive_slices(total_size_usd, initial_price, initial_liquidity)

        # Create execution
        execution = DepthAwareExecution(
            execution_id=execution_id,
            token_id=token_id,
            side=side,
            total_size_usd=total_size_usd,
            slices=slices,
            status=DepthAwareStatus.EXECUTING,
        )

        self._executions[execution_id] = execution
        self._stats["executions_started"] += 1

        try:
            await self._execute_slices(
                execution,
                executor_fn,
                price_check_fn,
                initial_price,
                initial_liquidity,
            )

            # Determine final status
            fill_ratio = execution.total_filled / total_size_usd if total_size_usd > 0 else 0

            if fill_ratio >= 0.99:
                execution.status = DepthAwareStatus.COMPLETED
                self._stats["executions_completed"] += 1
            elif fill_ratio >= 0.5:
                execution.status = DepthAwareStatus.EXECUTING  # Partial completion
            else:
                execution.status = DepthAwareStatus.INSUFFICIENT_LIQUIDITY
                self._stats["executions_insufficient_liquidity"] += 1

        except asyncio.TimeoutError:
            execution.status = DepthAwareStatus.FAILED
            execution.error = "Timeout"
            self._stats["executions_failed"] += 1

        except Exception as e:
            execution.status = DepthAwareStatus.FAILED
            execution.error = str(e)
            self._stats["executions_failed"] += 1

        execution.completed_at = time.time()

        # Calculate stats
        if execution.total_filled > 0:
            execution.avg_fill_price = execution.total_cost / execution.total_filled

        logger.info(
            f"[TWAP-D] Execution {execution_id} completed: "
            f"status={execution.status.value}, "
            f"filled=${execution.total_filled:.2f}/{total_size_usd:.2f}, "
            f"adjusted={execution.depth_adjusted_count}, "
            f"skipped={execution.skipped_count}"
        )

        return execution

    async def _execute_slices(
        self,
        execution: DepthAwareExecution,
        executor_fn: Callable,
        price_check_fn: Callable,
        initial_price: float,
        initial_liquidity: LiquidityEstimate,
    ) -> None:
        """Execute slices with depth monitoring."""
        start_time = time.time()
        cumulative_filled = 0.0
        depth_utilization_sum = 0.0
        depth_checks_count = 0

        for i, slice_ in enumerate(execution.slices):
            # Check timeout
            if time.time() - start_time > self.timeout:
                logger.warning(f"[TWAP-D] Execution {execution.execution_id} timed out")
                raise asyncio.TimeoutError()

            # Check price deviation periodically
            if i % 3 == 0:  # Every 3 slices
                try:
                    current_price = await price_check_fn(execution.token_id)
                    price_change = abs(current_price - initial_price) / initial_price

                    if price_change > self.price_threshold:
                        logger.warning(
                            f"[TWAP-D] Price moved {price_change * 100:.2f}%, "
                            f"cancelling remaining slices"
                        )
                        # Mark remaining as skipped
                        for remaining in execution.slices[i:]:
                            remaining.status = "skipped"
                            execution.skipped_count += 1
                        return

                except Exception as e:
                    logger.warning(f"[TWAP-D] Price check failed: {e}")

            # Check depth periodically
            if i % self.depth_check_interval == 0:
                order_book = await self._get_order_book(execution.token_id)
                self._stats["depth_checks"] += 1
                depth_checks_count += 1

                if order_book:
                    current_liquidity = self.liquidity_estimator.estimate_liquidity(
                        order_book,
                        execution.side,
                        slice_.price_limit,
                        execution.total_size_usd - cumulative_filled,
                    )

                    # Adjust remaining slices if liquidity changed
                    remaining_slices = execution.slices[i:]
                    if remaining_slices and current_liquidity.max_slice_size > 0:
                        for j, remaining_slice in enumerate(remaining_slices):
                            adjusted = self.liquidity_estimator.calculate_adaptive_slice_size(
                                current_liquidity,
                                remaining_slice.size_usd,
                                i + j,
                            )
                            if adjusted != remaining_slice.size_adjusted:
                                remaining_slice.size_adjusted = adjusted
                                execution.depth_adjusted_count += 1
                                self._stats["slices_adjusted"] += 1

                    # Track depth utilization
                    if current_liquidity.depth_at_price > 0:
                        util = min(1.0, slice_.size_adjusted / current_liquidity.depth_at_price)
                        depth_utilization_sum += util
                else:
                    current_liquidity = initial_liquidity

            # Check OBI if analyzer is available
            if self.obi_analyzer and order_book:
                obi_result = self.obi_analyzer.check_order_book(
                    order_book,
                    execution.side,
                    slice_.price_limit,
                )

                if not obi_result.passed:
                    logger.warning(
                        f"[TWAP-D] OBI check failed: {obi_result.reason}, "
                        f"skipping slice {slice_.slice_number}"
                    )
                    slice_.status = "skipped_obi"
                    execution.skipped_count += 1
                    self._stats["slices_skipped"] += 1
                    await asyncio.sleep(self.slice_interval)
                    continue

            # Execute slice with adjusted size
            actual_size = min(slice_.size_adjusted, execution.total_size_usd - cumulative_filled)

            if actual_size < 5.0:  # Below minimum
                slice_.status = "skipped_minimum"
                execution.skipped_count += 1
                continue

            slice_.size_adjusted = actual_size
            slice_.status = "executing"

            try:
                success = await executor_fn(slice_)

                if success:
                    slice_.status = "filled"
                    slice_.filled_at = time.time()
                    slice_.fill_price = slice_.price_limit

                    cumulative_filled += actual_size
                    execution.total_filled += actual_size
                    execution.total_cost += actual_size * slice_.price_limit

                    logger.info(
                        f"[TWAP-D] Slice {slice_.slice_number}/{slice_.total_slices} filled: "
                        f"${actual_size:.2f} @ {slice_.price_limit:.4f}"
                    )
                else:
                    slice_.status = "failed"
                    execution.skipped_count += 1

            except Exception as e:
                slice_.status = f"error: {e}"
                logger.error(f"[TWAP-D] Slice {slice_.slice_number} failed: {e}")

            # Wait before next slice
            if i < len(execution.slices) - 1:
                await asyncio.sleep(self.slice_interval)

        # Calculate avg depth utilization
        if depth_checks_count > 0:
            self._stats["avg_depth_utilization"] = depth_utilization_sum / depth_checks_count

    def get_execution(self, execution_id: str) -> DepthAwareExecution | None:
        """Get an execution by ID."""
        return self._executions.get(execution_id)

    def get_stats(self) -> dict:
        """Get depth-aware TWAP statistics."""
        return {
            **self._stats,
            "executions_total": sum(
                [
                    self._stats["executions_completed"],
                    self._stats["executions_insufficient_liquidity"],
                    self._stats["executions_failed"],
                ]
            ),
            "avg_adjustments_per_execution": (
                self._stats["slices_adjusted"] / max(1, self._stats["executions_started"])
            ),
        }


def create_depth_aware_twap(
    obi_analyzer=None,
    min_slice_size: float = 10.0,
    max_slices: int = 20,
) -> TWAPSlicerDepthAware:
    """
    Factory function to create Depth-Aware TWAP slicer.

    Args:
        obi_analyzer: Optional OBIAnalyzer instance
        min_slice_size: Minimum slice size
        max_slices: Maximum slices

    Returns:
        Configured TWAPSlicerDepthAware instance
    """
    return TWAPSlicerDepthAware(
        min_slice_size_usd=min_slice_size,
        max_slices=max_slices,
        obi_analyzer=obi_analyzer,
        liquidity_estimator=LiquidityEstimator(
            max_slippage_bps=50.0,
            min_depth_ratio=0.3,
        ),
    )
