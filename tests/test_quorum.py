"""Tests for the equal-weight QuorumEngine."""

import asyncio

import pytest

from weather_copy_bot.engine.quorum import (
    QuorumEngine,
    QuorumResult,
    WalletTradeSignal,
)


class FakeClock:
    """Deterministic monotonic clock for window testing."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_engine(**kwargs) -> tuple[QuorumEngine, FakeClock]:
    clock = FakeClock()
    kwargs.setdefault("clock", clock)
    return QuorumEngine(**kwargs), clock


def vote(
    wallet: str,
    token: str = "tok-1",
    side: str = "BUY",
    price: float = 0.50,
    size_usd: float = 0.0,
    timestamp: float | None = None,
    clock: FakeClock | None = None,
) -> WalletTradeSignal:
    if timestamp is None:
        timestamp = clock() if clock else 1_000_000.0
    return WalletTradeSignal(
        wallet_address=wallet,
        token_id=token,
        side=side,
        entry_price=price,
        size_usd=size_usd,
        timestamp=timestamp,
    )


class TestConstruction:
    """Constructor contract: equal weights, injectable clock."""

    def test_defaults(self):
        engine, _ = make_engine()

        assert engine.min_quorum_count == 2
        assert engine.window_seconds == 600.0
        assert engine.max_acceptable_price == 0.85

        stats = engine.get_stats()
        assert stats["signals_received"] == 0
        assert stats["signals_buffered"] == 0
        assert stats["signals_expired"] == 0
        assert stats["quorum_reached"] == 0
        assert stats["quorum_rejected"] == 0
        assert stats["duplicate_signals"] == 0
        assert stats["executed_keys"] == 0

    def test_custom_params(self):
        engine, _ = make_engine(
            min_quorum_count=3,
            window_seconds=120.0,
            max_acceptable_price=0.70,
        )

        assert engine.min_quorum_count == 3
        assert engine.window_seconds == 120.0
        assert engine.max_acceptable_price == 0.70


class TestBuffering:
    """Votes below the count threshold accumulate without firing."""

    def test_single_vote_buffers_without_firing(self):
        engine, clock = make_engine()

        result = engine.register_signal(vote("0xaaa", clock=clock))

        assert result is None
        stats = engine.get_stats()
        assert stats["signals_received"] == 1
        assert stats["signals_buffered"] == 1
        status = engine.get_buffer_status()
        assert len(status) == 1
        assert status[0]["votes"] == 1

    def test_same_wallet_revote_is_duplicate_not_new_vote(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", clock=clock))
        result = engine.register_signal(vote("0xaaa", clock=clock))

        assert result is None
        stats = engine.get_stats()
        assert stats["signals_buffered"] == 1
        assert stats["duplicate_signals"] == 1
        assert engine.get_buffer_status()[0]["votes"] == 1


class TestConsensus:
    """Distinct-wallet agreement mints one VWAP-priced result."""

    def test_two_distinct_wallets_fire_at_vwap(self):
        engine, clock = make_engine()
        t = clock()

        first = engine.register_signal(vote("0xaaa", price=0.40, size_usd=300.0, clock=clock))
        result = engine.register_signal(vote("0xbbb", price=0.60, size_usd=100.0, clock=clock))

        assert first is None
        assert isinstance(result, QuorumResult)
        assert result.token_id == "tok-1"
        assert result.side == "BUY"
        assert result.quorum_size == 2
        assert result.wallets == ("0xaaa", "0xbbb")
        # Size-weighted: (0.40*300 + 0.60*100) / 400 = 0.45
        assert result.vwap_price == pytest.approx(0.45)
        assert result.total_size_usd == pytest.approx(400.0)
        assert result.window_start == pytest.approx(t)

    def test_consensus_fires_exactly_once_then_locks(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", clock=clock))
        engine.register_signal(vote("0xbbb", clock=clock))
        late = engine.register_signal(vote("0xccc", clock=clock))

        assert late is None
        stats = engine.get_stats()
        assert stats["quorum_reached"] == 1
        assert stats["duplicate_signals"] == 1
        assert engine.get_buffer_status() == []

    def test_zero_sizes_fall_back_to_plain_mean(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", token="tok-mean", price=0.50, clock=clock))
        result = engine.register_signal(vote("0xbbb", token="tok-mean", price=0.70, clock=clock))

        assert result is not None
        assert result.vwap_price == pytest.approx(0.60)
        assert result.total_size_usd == pytest.approx(0.0)


class TestPriceGate:
    """The max_acceptable_price gate rejects expensive consensuses."""

    def test_expensive_vwap_rejected_once_per_composition(self):
        engine, clock = make_engine(max_acceptable_price=0.85)

        # First vote just buffers; the gate evaluates only once count is met.
        engine.register_signal(vote("0xaaa", price=0.90, clock=clock))
        assert engine.get_stats()["quorum_rejected"] == 0

        result = engine.register_signal(vote("0xbbb", price=0.95, clock=clock))
        assert result is None
        assert engine.get_stats()["quorum_rejected"] == 1

        # A third distinct wallet changes the composition, so it counts again.
        result = engine.register_signal(vote("0xccc", price=0.92, clock=clock))
        assert result is None
        stats = engine.get_stats()
        assert stats["quorum_rejected"] == 2
        assert stats["quorum_reached"] == 0
        assert engine.get_buffer_status()[0]["votes"] == 3


class TestWindowsAndTtl:
    """Votes expire after one window; execution locks after two."""

    def test_votes_expire_after_window(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", token="tok-x", clock=clock))
        clock.advance(601.0)
        result = engine.register_signal(vote("0xbbb", token="tok-x", clock=clock))

        assert result is None
        stats = engine.get_stats()
        assert stats["signals_expired"] == 1
        assert stats["quorum_reached"] == 0
        assert engine.get_buffer_status()[0]["votes"] == 1

    def test_executed_key_unlocks_after_double_window(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", token="tok-lock", clock=clock))
        engine.register_signal(vote("0xbbb", token="tok-lock", clock=clock))
        assert engine.get_stats()["quorum_reached"] == 1

        # Still inside 2x window: replays stay suppressed. Pruning runs
        # before the lock check, but the lock outlives one window.
        clock.advance(600.0)
        assert engine.register_signal(vote("0xddd", token="tok-lock", clock=clock)) is None
        assert engine.get_stats()["duplicate_signals"] == 1

        # Past 2x window the lock is pruned and a fresh quorum can form.
        clock.advance(700.0)
        engine.register_signal(vote("0xeee", token="tok-lock", clock=clock))
        result = engine.register_signal(vote("0xfff", token="tok-lock", clock=clock))

        assert result is not None
        assert engine.get_stats()["quorum_reached"] == 2

    def test_buffer_status_reports_time_remaining(self):
        engine, clock = make_engine()

        engine.register_signal(vote("0xaaa", clock=clock))
        clock.advance(250.0)

        status = engine.get_buffer_status()
        assert status[0]["time_remaining_seconds"] == pytest.approx(350.0)


class TestCleanupTask:
    """Background expiry loop lifecycle and effectiveness."""

    @pytest.mark.asyncio
    async def test_start_and_stop_lifecycle(self):
        engine, _ = make_engine()

        engine.start_cleanup_task(interval=0.01)
        assert engine._cleanup_task is not None

        await asyncio.sleep(0.05)
        await engine.stop_cleanup_task()

        assert engine._cleanup_task is None

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(self):
        engine, _ = make_engine()

        await engine.stop_cleanup_task()

        assert engine._cleanup_task is None

    @pytest.mark.asyncio
    async def test_background_loop_prunes_expired_votes(self):
        engine, clock = make_engine()
        engine.register_signal(vote("0xaaa", token="tok-bg", clock=clock))

        engine.start_cleanup_task(interval=0.01)
        try:
            clock.advance(601.0)
            await asyncio.sleep(0.05)

            assert engine.get_buffer_status() == []
            assert engine.get_stats()["signals_expired"] == 1
        finally:
            await engine.stop_cleanup_task()
