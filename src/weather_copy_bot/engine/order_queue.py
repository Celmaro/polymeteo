"""Order Queue with Deduplication for Concurrent Execution.

Prevents duplicate orders when multiple signals trigger the same market.
"""

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

logger = logging.getLogger(__name__)


class OrderState(str, Enum):
    """States for order lifecycle."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class Order:
    """An order in the queue."""

    order_id: str = field(default_factory=lambda: str(uuid4()))
    token_id: str = ""
    side: str = ""  # BUY or SELL
    size_usd: float = 0.0
    price: float = 0.0
    state: OrderState = OrderState.PENDING
    created_at: float = field(default_factory=time.time)
    submitted_at: float | None = None
    filled_at: float | None = None
    fill_amount: float = 0.0
    retries: int = 0
    max_retries: int = 3
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class QueuedOrder:
    """Wrapper for order in queue with priority."""

    order: Order
    priority: int = 0  # Higher = more priority
    added_at: float = field(default_factory=time.time)

    def __lt__(self, other: "QueuedOrder") -> bool:
        """Max-heap ordering by priority, FIFO within equal priority."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.added_at < other.added_at


class OrderQueue:
    """
    Thread-safe order queue with deduplication.

    Prevents:
    - Duplicate orders for same token/side
    - Concurrent submissions
    - Lost updates from race conditions
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        dedup_window_seconds: int = 60,
        max_retries: int = 3,
        rate_limit_per_second: int = 5,
    ):
        """
        Initialize OrderQueue.

        Args:
            max_queue_size: Maximum orders in queue
            dedup_window_seconds: Window for deduplication
            max_retries: Max retry attempts
            rate_limit_per_second: Max orders per second
        """
        self.max_queue_size = max_queue_size
        self.dedup_window = dedup_window_seconds
        self.max_retries = max_retries
        self.rate_limit = rate_limit_per_second

        # Main queue
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)

        # Deduplication index: {token_id_side: [order_ids, ...]}
        self._dedup_index: dict[str, list[str]] = defaultdict(list)

        # Active orders: {order_id: Order}
        self._active_orders: dict[str, Order] = {}

        # State machine locks: {token_id_side: asyncio.Lock}
        self._state_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Rate limiter
        self._last_submit_time = 0.0
        self._submit_count = 0

        # Stats
        self._stats = {
            "orders_queued": 0,
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_cancelled": 0,
            "orders_rejected": 0,
            "orders_failed": 0,
            "duplicates_rejected": 0,
            "rate_limited": 0,
        }

        # Background tasks
        self._cleanup_task: asyncio.Task | None = None
        self._processor_task: asyncio.Task | None = None
        self._running = False

    def _make_dedup_key(self, token_id: str, side: str) -> str:
        """Create deduplication key."""
        return f"{token_id}_{side.upper()}"

    def _is_duplicate(self, token_id: str, side: str) -> bool:
        """Check if order is duplicate within dedup window."""
        key = self._make_dedup_key(token_id, side)
        now = time.time()

        # Clean old entries
        self._dedup_index[key] = [
            oid
            for oid in self._dedup_index[key]
            if now - self._active_orders.get(oid, Order()).created_at < self.dedup_window
        ]

        # Check for existing order
        return len(self._dedup_index[key]) > 0

    def _add_to_dedup_index(self, order: Order) -> None:
        """Add order to deduplication index."""
        key = self._make_dedup_key(order.token_id, order.side)
        self._dedup_index[key].append(order.order_id)

    async def _check_rate_limit(self) -> bool:
        """Check and enforce rate limit."""
        now = time.time()

        # Reset counter every second
        if now - self._last_submit_time >= 1.0:
            self._last_submit_time = now
            self._submit_count = 0

        if self._submit_count >= self.rate_limit:
            self._stats["rate_limited"] += 1
            return False

        self._submit_count += 1
        return True

    async def enqueue(
        self,
        token_id: str,
        side: str,
        size_usd: float,
        price: float,
        metadata: dict | None = None,
        priority: int = 0,
    ) -> str | None:
        """
        Add an order to the queue.

        Returns order_id if queued, None if duplicate or queue full.
        """
        # Check for duplicate
        if self._is_duplicate(token_id, side):
            self._stats["duplicates_rejected"] += 1
            logger.warning(f"[Queue] Duplicate order rejected: {token_id} {side}")
            return None

        # Create order
        order = Order(
            token_id=token_id,
            side=side.upper(),
            size_usd=size_usd,
            price=price,
            metadata=metadata or {},
            max_retries=self.max_retries,
        )

        # Store in active orders
        self._active_orders[order.order_id] = order
        self._add_to_dedup_index(order)

        # Add to queue
        queued_order = QueuedOrder(order=order, priority=priority)

        try:
            self._queue.put_nowait(queued_order)
            self._stats["orders_queued"] += 1

            logger.info(
                f"[Queue] Order queued: {order.order_id[:8]}... "
                f"{order.side} {order.size_usd}@{order.price} "
                f"(token={order.token_id[:16]}...)"
            )

            return order.order_id

        except asyncio.QueueFull:
            # Queue full, remove from tracking
            del self._active_orders[order.order_id]
            key = self._make_dedup_key(token_id, side)
            self._dedup_index[key].remove(order.order_id)
            logger.error("[Queue] Queue full, order rejected")
            return None

    async def submit(self, order_id: str) -> bool:
        """
        Submit an order for execution.

        Returns True if submitted successfully.
        """
        if not await self._check_rate_limit():
            return False

        order = self._active_orders.get(order_id)
        if not order:
            return False

        # Get state lock
        key = self._make_dedup_key(order.token_id, order.side)
        async with self._state_locks[key]:
            if order.state != OrderState.PENDING:
                return False

            order.state = OrderState.SUBMITTED
            order.submitted_at = time.time()

        self._stats["orders_submitted"] += 1
        logger.info(f"[Queue] Order submitted: {order_id[:8]}...")

        return True

    async def mark_filled(self, order_id: str, fill_amount: float | None = None) -> bool:
        """Mark an order as filled."""
        order = self._active_orders.get(order_id)
        if not order:
            return False

        key = self._make_dedup_key(order.token_id, order.side)
        async with self._state_locks[key]:
            order.state = OrderState.FILLED
            order.filled_at = time.time()
            order.fill_amount = fill_amount or order.size_usd

        self._stats["orders_filled"] += 1
        logger.info(f"[Queue] Order filled: {order_id[:8]}... (amount={order.fill_amount})")

        return True

    async def mark_cancelled(self, order_id: str, reason: str = "") -> bool:
        """Mark an order as cancelled."""
        order = self._active_orders.get(order_id)
        if not order:
            return False

        key = self._make_dedup_key(order.token_id, order.side)
        async with self._state_locks[key]:
            order.state = OrderState.CANCELLED
            order.error = reason

        self._stats["orders_cancelled"] += 1
        logger.warning(f"[Queue] Order cancelled: {order_id[:8]}... ({reason})")

        return True

    async def mark_rejected(self, order_id: str, reason: str = "") -> bool:
        """Mark an order as rejected by exchange."""
        order = self._active_orders.get(order_id)
        if not order:
            return False

        order.retries += 1
        order.error = reason

        if order.retries >= order.max_retries:
            order.state = OrderState.REJECTED
            self._stats["orders_rejected"] += 1
            logger.error(f"[Queue] Order rejected after {order.retries} retries: {order_id[:8]}...")
            return False

        # Reset to pending for retry
        order.state = OrderState.PENDING
        logger.warning(
            f"[Queue] Order retry {order.retries}/{order.max_retries}: {order_id[:8]}..."
        )

        return True

    async def mark_failed(self, order_id: str, error: str) -> bool:
        """Mark an order as failed."""
        order = self._active_orders.get(order_id)
        if not order:
            return False

        order.state = OrderState.FAILED
        order.error = error

        self._stats["orders_failed"] += 1
        logger.error(f"[Queue] Order failed: {order_id[:8]}... ({error})")

        return True

    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        return self._active_orders.get(order_id)

    def get_order_state(self, token_id: str, side: str) -> OrderState | None:
        """Get current state of an order by token/side."""
        key = self._make_dedup_key(token_id, side)
        for order in self._active_orders.values():
            if self._make_dedup_key(order.token_id, order.side) == key:
                return order.state
        return None

    def get_pending_orders(self) -> list[Order]:
        """Get all pending orders."""
        return [o for o in self._active_orders.values() if o.state == OrderState.PENDING]

    def get_active_orders(self) -> list[Order]:
        """Get all active (non-terminal) orders."""
        terminal_states = {
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
        }
        return [o for o in self._active_orders.values() if o.state not in terminal_states]

    async def start(self, executor_fn: Callable[[Order], Awaitable[bool]]) -> None:
        """
        Start the queue processor.

        Args:
            executor_fn: Async function to execute orders
        """
        if self._running:
            return

        self._running = True
        self._executor_fn = executor_fn

        self._processor_task = asyncio.create_task(self._process_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("[Queue] Order queue processor started")

    async def stop(self) -> None:
        """Stop the queue processor."""
        self._running = False

        if self._processor_task:
            self._processor_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()

        logger.info("[Queue] Order queue processor stopped")

    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                # Get order from queue
                queued_order = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                order = queued_order.order

                # Submit order
                submitted = await self.submit(order.order_id)
                if not submitted:
                    continue

                # Execute order
                try:
                    success = await self._executor_fn(order)

                    if success:
                        await self.mark_filled(order.order_id)
                    else:
                        await self.mark_rejected(order.order_id, "Execution failed")

                except Exception as e:
                    await self.mark_failed(order.order_id, str(e))

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Queue] Processing error: {e}")

    async def _cleanup_loop(self) -> None:
        """Cleanup loop for stale orders."""
        while self._running:
            await asyncio.sleep(60)  # Cleanup every minute

            now = time.time()
            stale_threshold = 3600  # 1 hour

            for order_id, order in list(self._active_orders.items()):
                if order.state in {OrderState.PENDING, OrderState.SUBMITTED} and now - order.created_at > stale_threshold:
                        await self.mark_cancelled(order_id, "Stale order")

            # Cleanup dedup index
            for key in list(self._dedup_index.keys()):
                self._dedup_index[key] = [
                    oid for oid in self._dedup_index[key] if oid in self._active_orders
                ]

    def get_stats(self) -> dict:
        """Get queue statistics."""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "active_orders": len(self.get_active_orders()),
            "pending_orders": len(self.get_pending_orders()),
        }
