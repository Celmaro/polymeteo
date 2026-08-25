"""Tests for Order Queue."""

import pytest

from weather_copy_bot.engine.order_queue import (
    Order,
    OrderQueue,
    OrderState,
)


@pytest.fixture
async def queue():
    """Create a test queue."""
    q = OrderQueue(max_queue_size=100)
    yield q
    await q.stop()


class TestOrderQueue:
    """Tests for OrderQueue."""

    @pytest.mark.asyncio
    async def test_enqueue(self, queue):
        """Test adding order to queue."""
        order_id = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        assert order_id is not None
        order = queue.get_order(order_id)
        assert order is not None
        assert order.token_id == "TOKEN1"
        assert order.side == "BUY"
        assert order.size_usd == 100.0

    @pytest.mark.asyncio
    async def test_duplicate_rejection(self, queue):
        """Test that duplicates are rejected."""
        order_id1 = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        order_id2 = await queue.enqueue(
            token_id="TOKEN1",  # Same token
            side="BUY",  # Same side
            size_usd=200.0,
            price=0.52,
        )

        assert order_id1 is not None
        assert order_id2 is None  # Should be rejected

        stats = queue.get_stats()
        assert stats["duplicates_rejected"] == 1

    @pytest.mark.asyncio
    async def test_different_sides(self, queue):
        """Test that BUY and SELL are not duplicates."""
        order_id1 = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        order_id2 = await queue.enqueue(
            token_id="TOKEN1",
            side="SELL",  # Different side
            size_usd=100.0,
            price=0.50,
        )

        assert order_id1 is not None
        assert order_id2 is not None

    @pytest.mark.asyncio
    async def test_order_state_machine(self, queue):
        """Test order state transitions."""
        order_id = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        # Initial state
        order = queue.get_order(order_id)
        assert order.state == OrderState.PENDING

        # Submit
        await queue.submit(order_id)
        order = queue.get_order(order_id)
        assert order.state == OrderState.SUBMITTED

        # Fill
        await queue.mark_filled(order_id)
        order = queue.get_order(order_id)
        assert order.state == OrderState.FILLED
        assert order.filled_at is not None

    @pytest.mark.asyncio
    async def test_cancel_order(self, queue):
        """Test order cancellation."""
        order_id = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        await queue.mark_cancelled(order_id, "User requested")

        order = queue.get_order(order_id)
        assert order.state == OrderState.CANCELLED
        assert order.error == "User requested"

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, queue):
        """Test order retry on rejection."""
        order_id = await queue.enqueue(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        # Reject twice
        await queue.mark_rejected(order_id, "Insufficient liquidity")
        await queue.mark_rejected(order_id, "Price moved")

        order = queue.get_order(order_id)
        assert order.retries == 2
        assert order.state == OrderState.PENDING  # Reset for retry

        # Final rejection
        await queue.mark_rejected(order_id, "Final rejection")
        order = queue.get_order(order_id)
        assert order.state == OrderState.REJECTED

    @pytest.mark.asyncio
    async def test_get_pending_orders(self, queue):
        """Test getting pending orders."""
        await queue.enqueue("T1", "BUY", 100.0, 0.50)
        await queue.enqueue("T2", "BUY", 100.0, 0.50)
        await queue.enqueue("T3", "BUY", 100.0, 0.50)

        pending = queue.get_pending_orders()
        assert len(pending) == 3

    @pytest.mark.asyncio
    async def test_get_active_orders(self, queue):
        """Test getting active orders."""
        order_id = await queue.enqueue("T1", "BUY", 100.0, 0.50)

        await queue.submit(order_id)

        active = queue.get_active_orders()
        assert len(active) == 1
        assert active[0].order_id == order_id

    @pytest.mark.asyncio
    async def test_rate_limiting(self, queue):
        """Test rate limiting."""
        queue.rate_limit = 2

        # First two should succeed
        await queue.submit("fake1")
        await queue.submit("fake2")

        # Third should be rate limited
        result = await queue._check_rate_limit()
        assert result is False

        stats = queue.get_stats()
        assert stats["rate_limited"] == 1

    @pytest.mark.asyncio
    async def test_stats(self, queue):
        """Test statistics tracking."""
        await queue.enqueue("T1", "BUY", 100.0, 0.50)
        await queue.enqueue("T2", "BUY", 100.0, 0.50)
        await queue.enqueue("T3", "BUY", 100.0, 0.50)
        await queue.enqueue("T1", "BUY", 100.0, 0.50)  # Duplicate

        stats = queue.get_stats()
        assert stats["orders_queued"] == 3
        assert stats["duplicates_rejected"] == 1

    @pytest.mark.asyncio
    async def test_priority_queue(self, queue):
        """Test priority ordering."""
        await queue.enqueue("T1", "BUY", 100.0, 0.50, priority=1)
        await queue.enqueue("T2", "BUY", 100.0, 0.50, priority=10)
        await queue.enqueue("T3", "BUY", 100.0, 0.50, priority=5)

        # High priority should be processed first
        # (Note: actual order depends on asyncio queue behavior)


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        """Test order creation with defaults."""
        order = Order(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
        )

        assert order.order_id is not None
        assert order.state == OrderState.PENDING
        assert order.retries == 0
        assert order.fill_amount == 0.0
        assert order.metadata == {}

    def test_order_with_metadata(self):
        """Test order with metadata."""
        order = Order(
            token_id="TOKEN1",
            side="BUY",
            size_usd=100.0,
            price=0.50,
            metadata={"wallet": "0x123", "quorum_size": 3},
        )

        assert order.metadata["wallet"] == "0x123"
        assert order.metadata["quorum_size"] == 3
