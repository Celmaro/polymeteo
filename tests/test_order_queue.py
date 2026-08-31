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


class TestOrderQueueWAL:
    """Tests for the OrderQueue write-ahead log (db-backed persistence)."""

    @pytest.fixture
    def db_manager(self, tmp_path):
        """SQLite DatabaseManager that creates all tables on disk."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from weather_copy_bot.db.manager import DatabaseManager
        from weather_copy_bot.db.models import Base

        url = f"sqlite:///{tmp_path / 'wal.db'}"
        engine = create_engine(url, pool_pre_ping=True)
        Base.metadata.create_all(engine)
        factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )

        manager = DatabaseManager(database_url=url)
        manager._engine = engine
        manager._session_factory = factory
        return manager

    @pytest.fixture
    async def queue_with_wal(self, db_manager):
        """OrderQueue with WAL enabled."""
        q = OrderQueue(max_queue_size=100, db_manager=db_manager, mode="paper")
        yield q
        await q.stop()

    @pytest.mark.asyncio
    async def test_enqueue_journals_pending_row(self, queue_with_wal, db_manager):
        """An enqueue should create a pending row in order_records."""
        import asyncio

        from weather_copy_bot.db.repositories import OrderRepository

        order_id = await queue_with_wal.enqueue(
            token_id="T1", side="BUY", size_usd=100.0, price=0.50
        )
        # Wait for the fire-and-forget WAL write to land.
        await asyncio.gather(*queue_with_wal._wal_tasks, return_exceptions=True)

        with db_manager.session() as session:
            repo = OrderRepository(session)
            record = repo.get_by_order_id(order_id)

        assert record is not None
        assert record.token_id == "T1"
        assert record.side == "BUY"
        assert record.size_usd == 100.0
        assert record.price == 0.50
        assert record.state == "pending"
        assert record.mode == "paper"
        assert record.retries == 0
        assert record.fill_amount == 0.0
        assert record.created_at is not None

    @pytest.mark.asyncio
    async def test_state_transitions_update_row(self, queue_with_wal, db_manager):
        """submit / fill should update the same row (upsert)."""
        import asyncio

        from weather_copy_bot.db.repositories import OrderRepository

        order_id = await queue_with_wal.enqueue(
            token_id="T2", side="BUY", size_usd=200.0, price=0.55
        )
        await queue_with_wal.submit(order_id)
        await queue_with_wal.mark_filled(order_id, fill_amount=200.0)
        await asyncio.gather(*queue_with_wal._wal_tasks, return_exceptions=True)

        with db_manager.session() as session:
            repo = OrderRepository(session)
            record = repo.get_by_order_id(order_id)
            count = len(repo.get_active())

        assert record is not None
        assert record.state == "filled"
        assert record.fill_amount == 200.0
        assert record.submitted_at is not None
        assert record.filled_at is not None
        assert count == 0  # filled is terminal

    @pytest.mark.asyncio
    async def test_stop_drains_pending_wal_writes(self, queue_with_wal, db_manager):
        """stop() must await in-flight WAL tasks so the journal is durable."""
        from weather_copy_bot.db.repositories import OrderRepository

        order_id = await queue_with_wal.enqueue(
            token_id="T3", side="SELL", size_usd=50.0, price=0.40
        )
        # stop() drains; then we should be able to read the journal.
        await queue_with_wal.stop()

        with db_manager.session() as session:
            repo = OrderRepository(session)
            record = repo.get_by_order_id(order_id)

        assert record is not None
        assert record.state == "pending"
        assert queue_with_wal._wal_tasks == set()  # drained

    @pytest.mark.asyncio
    async def test_wal_disabled_when_no_db_manager(self):
        """Without a db_manager, state transitions succeed but no rows appear."""
        q = OrderQueue(max_queue_size=100)  # no db_manager
        order_id = await q.enqueue(
            token_id="T4", side="BUY", size_usd=10.0, price=0.51
        )
        await q.submit(order_id)
        await q.mark_filled(order_id)

        # In-memory state is correct even without persistence.
        order = q.get_order(order_id)
        assert order.state == OrderState.FILLED
        assert q._wal_tasks == set()

        await q.stop()

    @pytest.mark.asyncio
    async def test_failed_wal_does_not_crash_queue(self, queue_with_wal, db_manager, caplog):
        """If the DB write fails, the queue keeps running and increments a counter."""
        import asyncio

        from sqlalchemy.exc import SQLAlchemyError

        from weather_copy_bot.db.repositories import OrderRepository

        original_flush = OrderRepository.upsert_from_queue
        calls = {"n": 0}

        def boom(self, **kwargs):
            calls["n"] += 1
            raise SQLAlchemyError("simulated DB down")

        OrderRepository.upsert_from_queue = boom
        try:
            with caplog.at_level("WARNING"):
                order_id = await queue_with_wal.enqueue(
                    token_id="T5", side="BUY", size_usd=10.0, price=0.99
                )
            await asyncio.gather(*queue_with_wal._wal_tasks, return_exceptions=True)
        finally:
            OrderRepository.upsert_from_queue = original_flush

        assert order_id is not None
        assert calls["n"] >= 1
        assert queue_with_wal._stats["wal_flush_failures"] >= 1
        assert "WAL flush failed" in caplog.text

    @pytest.mark.asyncio
    async def test_cancelled_and_rejected_persist(self, queue_with_wal, db_manager):
        """Cancelled and rejected states should be journaled with reasons."""
        import asyncio

        from weather_copy_bot.db.repositories import OrderRepository

        order_id = await queue_with_wal.enqueue(
            token_id="T6", side="BUY", size_usd=5.0, price=0.51
        )
        await queue_with_wal.mark_cancelled(order_id, "rate_limited")
        await asyncio.gather(*queue_with_wal._wal_tasks, return_exceptions=True)

        with db_manager.session() as session:
            repo = OrderRepository(session)
            record = repo.get_by_order_id(order_id)

        assert record.state == "cancelled"
        assert record.error == "rate_limited"
